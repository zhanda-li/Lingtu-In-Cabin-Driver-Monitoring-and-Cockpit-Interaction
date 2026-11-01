import sys
import unittest
import ast
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch
import threading
import types
import itertools
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
BASELINE = '97f11b7'
sys.path.insert(0, str(ROOT/'src'))
from face_roi_yolo import crop_roi, REGIONS, Temporal, FaceRoiYolo, AsyncFaceRoiYolo


class ShadowTests(unittest.TestCase):
    def test_async_invalid_roi_cannot_reuse_previous_closed_result(self):
        fake = Mock()
        fake.process.return_value = dict(eye_status='invalid',yawn_status='invalid')
        with patch('face_roi_yolo.FaceRoiYolo',return_value=fake):
            worker = AsyncFaceRoiYolo('','')
        try:
            with worker._state_lock:
                worker.latest = dict(sample_timestamp=0.,eye_status='active',eye_event='long_closure')
            result = worker.process(np.zeros((100,100,3),np.uint8),{},.2,.1)
            self.assertEqual(result['eye_status'],'invalid')
            self.assertEqual(result['eye_event'],'invalid')
        finally:
            worker.close(); worker.worker.join(2)

    def test_async_result_finishing_after_face_loss_is_discarded(self):
        entered,release = threading.Event(),threading.Event()
        second_entered,second_release = threading.Event(),threading.Event()
        calls = []
        def slow(*args):
            calls.append(args)
            if len(calls)==1:
                entered.set(); release.wait(3)
            else:
                second_entered.set(); second_release.wait(3)
            return dict(eye_status='active',yawn_status='inactive')
        fake = Mock(); fake.process.side_effect = slow
        with patch('face_roi_yolo.FaceRoiYolo',return_value=fake):
            worker = AsyncFaceRoiYolo('','')
        points = {i:np.array([30.+j*2,40.+j%2]) for ids in REGIONS.values() for j,i in enumerate(ids)}
        image = np.zeros((100,100,3),np.uint8)
        try:
            worker.process(image,points,.2,0)
            self.assertTrue(entered.wait(2))
            worker.process(image,None,None,.1)
            worker.process(image,points,.2,.2)
            release.set()
            self.assertTrue(second_entered.wait(2))
            with worker._state_lock:
                self.assertIsNone(worker.latest)
        finally:
            worker.close(); release.set(); second_release.set(); worker.worker.join(3)

    def test_all_fusion_levels_and_gates_against_original(self):
        def fusion(source):
            picked = []
            names = {'l_face','l_base','l_yawn','l_eye','l_head','l_fused'}
            for node in ast.walk(ast.parse(source)):
                if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
                    if node.targets[0].id in names and isinstance(node.value,(ast.IfExp,ast.Call)):
                        picked.append(node)
            picked.sort(key=lambda n:n.lineno)
            self.assertEqual([n.targets[0].id for n in picked],['l_face','l_base','l_yawn','l_eye','l_head','l_fused'])
            return compile(ast.Module(body=picked,type_ignores=[]),'fusion_regression','exec')
        original = subprocess.check_output(['git','show',f'{BASELINE}:src/fuse.py'],cwd=ROOT).decode('utf-8')
        before = fusion(original)
        after = fusion((ROOT/'src/fuse.py').read_text(encoding='utf-8'))
        observed = set()
        for l1,l2,gate,present,yawn,eye,head in itertools.product(range(4),range(4),*[ [False,True] ]*5):
            inputs = dict(l1=l1,l2=l2,gate=gate,face=object() if present else None,
                          yawn_on=yawn,eye_on=eye,head_on=head,B2_MAX_LEVEL=2,
                          args=types.SimpleNamespace(yawn_action='level',eye_level=2,head_level=3))
            a,b = dict(inputs),dict(inputs,yolo_shadow={'eye_event':'long_closure','yawn_event':'yawn_candidate','risk':99})
            exec(before,a); exec(after,b)
            self.assertEqual(a['l_fused'],b['l_fused'])
            observed.add(b['l_fused'])
        self.assertEqual(observed,{0,1,2,3})

    def test_uncertain_eyes_do_not_create_blink(self):
        t = Temporal()
        t.update(0,0,0,0,.1)
        out = t.update(.2,.5,.5,0,.1)
        self.assertEqual(out['eye_event'],'none')
        self.assertEqual(out['eye_left_status'],'uncertain')

    def test_ui_state_shadow_serialization(self):
        sys.path.insert(0, str(ROOT))
        from ui.state import State
        state = State()
        before = state.to_json()
        self.assertNotIn('yolo_shadow', before)
        state.yolo_shadow = {'mode':'shadow','eye_event':'long_closure'}
        state.derive({})
        enabled = state.to_json()
        self.assertEqual(enabled['yolo_shadow'],state.yolo_shadow)
        for k in ['l_fused','l1','l2']:
            self.assertEqual(before[k],enabled[k])

    def test_all_ui_levels_match_original_with_shadow_evidence(self):
        from ui.state import State
        source = subprocess.check_output(['git','show',f'{BASELINE}:ui/state.py'],cwd=ROOT).decode('utf-8')
        baseline = types.ModuleType('baseline_ui_state')
        with patch.dict(sys.modules, {baseline.__name__:baseline}):
            exec(compile(source,'baseline_ui_state.py','exec'),baseline.__dict__)
        for level in range(4):
            kwargs = dict(l_fused=level,l1=3 if level==3 else 0,l2=min(level,2),
                          p_fat=level*.3,perclos=level*.2,src='pose' if level==3 else 'face')
            before = baseline.State(**kwargs).derive({}).to_json()
            state = State(**kwargs)
            state.yolo_shadow = {'mode':'shadow','eye_event':'long_closure','yawn_event':'yawn_candidate'}
            after = state.derive({}).to_json()
            after.pop('yolo_shadow')
            self.assertEqual(before,after)

    def test_async_queue_bounded_and_loss_invalidates(self):
        entered, release = threading.Event(), threading.Event()
        fake = Mock()
        def slow(*args):
            entered.set(); release.wait(3)
            return dict(eye_status='active', yawn_status='inactive')
        fake.process.side_effect = slow
        with patch('face_roi_yolo.FaceRoiYolo', return_value=fake):
            worker = AsyncFaceRoiYolo('', '')
        try:
            image = np.zeros((100,100,3), np.uint8)
            points = {i:np.array([20.,30.]) for i in REGIONS['left']}
            worker.process(image, points, .2, 0)
            self.assertTrue(entered.wait(2))
            for i in range(10):
                worker.process(image, points, .2, i*.01)
            self.assertLessEqual(worker.pending.qsize(), 1)
            self.assertEqual(worker.process(image, None, None, .2)['eye_status'], 'invalid')
        finally:
            worker.close(); release.set(); worker.worker.join(3)

    def test_onnx_preprocessing_matches_ultralytics(self):
        from yolo_runtime import preprocess, OnnxClassifier
        from ultralytics.data.augment import classify_transforms
        from PIL import Image
        rng = np.random.default_rng(42)
        for h,w in [(91,140),(140,91),(96,96),(93,130)]:
            image = rng.integers(0,256,(h,w,3),dtype=np.uint8)
            expected = classify_transforms(224)(Image.fromarray(image[:,:,::-1])).numpy()[None]
            np.testing.assert_allclose(preprocess(image), expected, atol=1e-7)
        for name,pos,neg in [('best',{'open'},{'closed'}),('best_yawn',{'yawn'},{'no_yawn'})]:
            native = __import__('face_roi_yolo').Classifier(ROOT/f'models/yolo_shadow/{name}.pt',pos,neg)
            onnx = OnnxClassifier(ROOT/f'models/yolo_shadow/{name}.onnx',pos,neg)
            self.assertAlmostEqual(native(image), onnx(image), places=5)

    def test_rknn_missing_runtime_falls_back_to_real_onnx(self):
        from yolo_runtime import OnnxClassifier, RknnClassifier
        path = ROOT/'models/yolo_shadow/best.onnx'
        with patch.dict(sys.modules, {'rknnlite':None}):
            fallback = RknnClassifier(path, {'open'}, {'closed'})
        cpu = OnnxClassifier(path, {'open'}, {'closed'})
        image = np.full((90,140,3),127,np.uint8)
        self.assertEqual(fallback.backend, 'onnx_cpu_fallback')
        self.assertIsNotNone(fallback.fallback_reason)
        self.assertAlmostEqual(fallback(image), cpu(image), places=7)
        fallback.close()

    def test_disabled_face_detect_matches_original(self):
        import face
        source = subprocess.check_output(['git','show',f'{BASELINE}:src/face.py'],cwd=ROOT).decode('utf-8')
        original = {'__file__':str(ROOT/'src/face.py'), '__name__':'baseline_face'}
        exec(compile(source, 'baseline_face.py', 'exec'), original)
        old = original['FaceExtractor'].__new__(original['FaceExtractor'])
        new = face.FaceExtractor.__new__(face.FaceExtractor)
        new.yolo_shadow = None
        # Identical landmark observations isolate behavior from MediaPipe nondeterminism.
        points = [types.SimpleNamespace(x=.2+(i%20)*.02,y=.2+(i//20)*.015) for i in range(478)]
        for extractor in [old,new]:
            extractor._mp = Mock()
            extractor._last_ts = -1
            extractor.running_mode = 'VIDEO'
            extractor._landmarker = Mock()
        image = np.zeros((120,160,3),np.uint8)
        for ts, found in [(0,True),(67,False),(134,True)]:
            result = types.SimpleNamespace(face_landmarks=[points] if found else [],
                                           facial_transformation_matrixes=[np.eye(4)])
            for extractor in [old,new]:
                extractor._landmarker.detect_for_video.return_value = result
            a,b = old.detect(image,ts),new.detect(image,ts)
            if not found:
                self.assertIsNone(a); self.assertIsNone(b)
            else:
                self.assertEqual(a.keys(),b.keys())
                for key in a:
                    if key == 'P':
                        for i in a[key]:
                            np.testing.assert_array_equal(a[key][i],b[key][i])
                    else:
                        np.testing.assert_equal(a[key],b[key])

    def test_roi(self):
        image = np.zeros((100, 100, 3), np.uint8)
        for ids in REGIONS.values():
            points = {i: [30+j*3, 40+j%2] for j, i in enumerate(ids)}
            self.assertGreater(crop_roi(image, points, ids).size, 0)
            points[ids[0]] = [-2, 10]
            self.assertIsNone(crop_roi(image, points, ids))
        self.assertIsNone(crop_roi(image, None, REGIONS['left']))
        self.assertIsNone(crop_roi(image, {}, REGIONS['mouth']))

    def test_invalid_and_gap(self):
        t = Temporal()
        t.update(0, 0, 0, 1, .8)
        self.assertEqual(t.update(.1, None, None, None, None)['eye_event'], 'invalid')
        self.assertEqual(t.update(3, 0, 0, 1, .8)['eye_closed_duration'], 0)

    def test_long_closure_and_single_event(self):
        t = Temporal()
        out = [t.update(i/10, 0, 0, 0, .1) for i in range(20)]
        self.assertEqual(sum(x['eye_event']=='long_closure' for x in out), 1)

    def test_blink(self):
        t = Temporal()
        t.update(0, 0, 0, 0, .1)
        t.update(.1, 0, 0, 0, .1)
        out = t.update(.3, 1, 1, 0, .1)
        self.assertEqual(out['eye_event'], 'blink')

    def test_talking_and_yawn_synthetic(self):
        for mouth, mar, expected in [(1, .2, 0), (0, .8, 0), (1, .8, 1)]:
            t = Temporal()
            out = [t.update(i/10, 1, 1, mouth, mar) for i in range(30)]
            self.assertEqual(sum(x['yawn_event']=='yawn_candidate' for x in out), expected)

    def test_missing_face_does_not_infer(self):
        detector = FaceRoiYolo.__new__(FaceRoiYolo)
        detector.eye = Mock(); detector.mouth = Mock(); detector.temporal = Temporal()
        out = detector.process(np.zeros((100,100,3)), None, None, 0)
        detector.eye.assert_not_called(); detector.mouth.assert_not_called()
        self.assertEqual(out['yawn_status'], 'invalid')

    def test_original_algorithms_unchanged(self):
        class PlatformOnly(ast.NodeTransformer):
            # Approved compatibility surfaces only. All inference, scheduling,
            # feature and fusion code still compares against the original AST.
            def visit_ImportFrom(self, node):
                return None if node.module == 'src.capture_backend' else node

            def visit_ClassDef(self, node):
                skip = {'CameraSource': '__init__', 'TTSWorker': '_run'}.get(node.name)
                node.body = [n for n in node.body
                             if not (isinstance(n, ast.FunctionDef) and n.name == skip)]
                return self.generic_visit(node)

            def visit_Call(self, node):
                # --cam now accepts indices and Linux paths. No other CLI
                # argument or algorithm expression is exempt from comparison.
                if (isinstance(node.func, ast.Attribute) and node.func.attr == 'add_argument'
                        and node.args and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value == '--cam'):
                    for kw in node.keywords:
                        if kw.arg == 'type' and isinstance(kw.value, ast.Name) and kw.value.id == 'camera_device':
                            kw.value.id = 'int'
                    node.keywords = [k for k in node.keywords if k.arg != 'help']
                return self.generic_visit(node)

        for file in ['src/fuse.py', 'src/live.py', 'src/model.py', 'src/pose.py']:
            before = subprocess.check_output(['git','show',f'{BASELINE}:{file}'], cwd=ROOT).decode('utf-8')
            self.assertEqual(ast.dump(PlatformOnly().visit(ast.parse(before))),
                             ast.dump(PlatformOnly().visit(ast.parse((ROOT/file).read_text(encoding='utf-8')))))
        before = ast.parse(subprocess.check_output(['git','show',f'{BASELINE}:src/face.py'], cwd=ROOT).decode('utf-8'))
        after = ast.parse((ROOT/'src/face.py').read_text(encoding='utf-8'))
        for node in before.body:
            if isinstance(node, ast.FunctionDef):
                other = next(n for n in after.body if isinstance(n, ast.FunctionDef) and n.name == node.name)
                self.assertEqual(ast.dump(node), ast.dump(other))

if __name__ == '__main__':
    unittest.main()
