import sys
import unittest
import ast
import subprocess
from pathlib import Path
from unittest.mock import Mock
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from face_roi_yolo import crop_roi, REGIONS, Temporal, FaceRoiYolo


class ShadowTests(unittest.TestCase):
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
        for file in ['src/fuse.py', 'src/live.py', 'src/model.py', 'src/pose.py']:
            before = subprocess.check_output(['git','show',f'HEAD:{file}'], cwd=ROOT).decode('utf-8')
            self.assertEqual(ast.dump(ast.parse(before)), ast.dump(ast.parse((ROOT/file).read_text(encoding='utf-8'))))
        before = ast.parse(subprocess.check_output(['git','show','HEAD:src/face.py'], cwd=ROOT).decode('utf-8'))
        after = ast.parse((ROOT/'src/face.py').read_text(encoding='utf-8'))
        for node in before.body:
            if isinstance(node, ast.FunctionDef):
                other = next(n for n in after.body if isinstance(n, ast.FunctionDef) and n.name == node.name)
                self.assertEqual(ast.dump(node), ast.dump(other))

if __name__ == '__main__':
    unittest.main()
