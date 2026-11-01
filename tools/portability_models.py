"""Frozen real inputs and independent original-model CPU tests; no live devices.

prepare -> run on PC -> copy bundle/project -> run on ARM64 -> compare reports.
Subprocess workers exit after flushing reports to avoid the known MediaPipe
destructor delay. This harness never changes production model or fusion code.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src'), str(ROOT / 'ui')]
KINDS = ('pose', 'face', 'transformer', 'eye', 'mouth')
SOURCES = ['config.py','src/pose.py','src/face.py','src/model.py','src/live.py',
           'src/yolo_runtime.py','src/face_roi_yolo.py','tools/portability_models.py']


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): digest.update(block)
    return digest.hexdigest()


def source_sha(path):
    # Git may check out identical Python sources as CRLF on Windows and LF on
    # Linux. Only source line endings are normalized; model/input bytes are not.
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n',b'\n')).hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def bundle_file(bundle, relative):
    path = (bundle / relative).resolve()
    if not path.is_relative_to(bundle.resolve()): raise ValueError('Bundle path escapes its root')
    return path


def verify_bundle(bundle):
    manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    for name, record in {**manifest['inputs'], **manifest['models']}.items():
        if sha(bundle_file(bundle, record['path'])) != record['sha256']:
            raise ValueError(f'Bundle SHA256 mismatch: {name}')
    for name, expected in manifest['source_sha256'].items():
        if source_sha(ROOT / name) != expected: raise ValueError(f'Algorithm/harness source differs: {name}')
    return manifest


def child(bundle, output, kind):
    env = dict(os.environ, OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
               DMS_YOLO_SHADOW='0', DMS_YOLO_LOG='', DMS_FUSION_LOG='')
    command = [sys.executable, str(Path(__file__).resolve()), '_worker', '--bundle', str(bundle),
               '--out', str(output), '--kind', kind]
    proc = subprocess.run(command, env=env, cwd=ROOT, capture_output=True, timeout=120)
    (output / f'{kind}.log').write_bytes(proc.stdout + b'\n' + proc.stderr)
    report = output / f'{kind}.json'
    if not report.exists():
        write_json(report, dict(kind=kind, passed=False, error=f'worker exit {proc.returncode}; see log',
                                board_validation='待板端验证'))
    return proc.returncode == 0 and json.loads(report.read_text(encoding='utf-8')).get('passed') is True


def prepare(args):
    import cv2
    import config as C
    from live import load_infer_model, OnlineNormalizer
    from face_roi_yolo import crop_roi, REGIONS
    from yolo_runtime import preprocess
    bundle = args.out.resolve()
    if bundle.exists(): raise FileExistsError('Choose a new bundle directory; existing results are never overwritten')
    bundle.mkdir(parents=True)
    (bundle / 'models').mkdir(); (bundle / 'inputs').mkdir()
    model, mean, std, classes, window = load_infer_model(args.checkpoint)
    del model
    if args.frames < window: raise ValueError(f'Need >= checkpoint window ({window}) real 15Hz frames')
    frames = []; indices = []
    cap = cv2.VideoCapture(str(args.video))
    try:
        if not cap.isOpened(): raise RuntimeError('Cannot open local input video')
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not np.isfinite(fps) or fps <= 0: raise ValueError('Video has no reliable FPS')
        current = -1; frame = None
        for i in range(args.frames):
            target = int(np.floor((args.start + i / C.TARGET_FPS) * fps))
            while current < target:
                ok, frame = cap.read(); current += 1
                if not ok or frame is None: raise ValueError('Video too short; refusing to pad/fabricate frames')
            frames.append(frame.copy()); indices.append(current)
    finally:
        cap.release()
    np.savez_compressed(bundle / 'inputs/frames.npz', bgr=np.stack(frames),
                        timestamp_ms=np.rint(np.arange(args.frames) * 1000 / C.TARGET_FPS).astype(np.int64))
    paths = dict(pose=C.MODELS_DIR / f'pose_landmarker_{C.POSE_MODEL_NAME}.task',
                 face=C.MODELS_DIR / 'face_landmarker.task', transformer=args.checkpoint,
                 eye=C.MODELS_DIR / 'yolo_shadow/best.onnx', mouth=C.MODELS_DIR / 'yolo_shadow/best_yawn.onnx')
    manifest = dict(schema=1, board_validation='待板端验证', source_video_sha256=sha(args.video),
                    source_frame_indices=indices, source_fps=fps, sample_hz=C.TARGET_FPS,
                    window=window, classes=classes, inputs={}, models={},
                    source_sha256={name: source_sha(ROOT / name) for name in SOURCES},
                    source_hash_normalization='CRLF to LF only; model and input hashes are raw bytes',
                    note='Real video frames; no synthetic labels or accuracy claim; preprocessing frozen on PC')
    for name, path in paths.items():
        relative = ('models/' + Path(path).name) if name == 'pose' else f'models/{name}{Path(path).suffix}'
        shutil.copyfile(path, bundle / relative)
        manifest['models'][name] = dict(path=relative, sha256=sha(bundle / relative))
    manifest['inputs']['frames'] = dict(path='inputs/frames.npz', sha256=sha(bundle / 'inputs/frames.npz'))
    write_json(bundle / 'manifest.json', manifest)
    bootstrap = bundle / 'preparation'; bootstrap.mkdir()
    for kind in ('pose','face'):
        if not child(bundle, bootstrap, kind): raise RuntimeError(f'{kind} preparation failed; see preparation logs')
    with np.load(bootstrap / 'pose.npz', allow_pickle=False) as data:
        if not data['valid'][:window].all():
            raise ValueError('First complete window contains missing poses; choose another real video/start time')
        normalizer = OnlineNormalizer()
        values = np.stack([normalizer.push(lm) for lm in data['landmarks'][:window]])
    tensor = np.ascontiguousarray(((values - mean) / std)[None], dtype=np.float32)
    if not np.isfinite(tensor).all(): raise ValueError('Invalid original Transformer normalization')
    np.save(bundle / 'inputs/transformer.npy', tensor, allow_pickle=False)
    with np.load(bootstrap / 'face.npz', allow_pickle=False) as data:
        candidates = np.flatnonzero(data['valid'])
        if not len(candidates): raise ValueError('No face found; cannot create real eye/mouth ROI inputs')
        index = int(candidates[0])
        points = dict(zip(data['point_ids'].tolist(), data['points'][index]))
    for name, region in [('left','left'), ('right','right'), ('mouth','mouth')]:
        roi = crop_roi(frames[index], points, REGIONS[region])
        if roi is None: raise ValueError(f'Invalid real ROI: {name}')
        np.save(bundle / f'inputs/{name}_roi.npy', roi, allow_pickle=False)
        np.save(bundle / f'inputs/{name}_tensor.npy', preprocess(roi), allow_pickle=False)
    manifest['roi_frame_index'] = index
    for path in sorted((bundle / 'inputs').iterdir()):
        manifest['inputs'][path.stem] = dict(path=path.relative_to(bundle).as_posix(), sha256=sha(path))
    # The original entry was named frames already; no duplicate manifest keys.
    write_json(bundle / 'manifest.json', manifest)
    print(f'Prepared frozen real-input bundle: {bundle}')


def worker(args):
    report = dict(schema=1, kind=args.kind, passed=False, board_validation='待板端验证',
                  platform=sys.platform, machine=__import__('platform').machine(), python=sys.version,
                  packages={}, device='cpu')
    start = time.perf_counter()
    try:
        manifest = verify_bundle(args.bundle)
        report.update(manifest_sha256=sha(args.bundle / 'manifest.json'),
                      model_sha256=manifest['models'][args.kind]['sha256'])
        for name in ('mediapipe','torch','onnxruntime','numpy','Pillow','opencv-contrib-python'):
            try: report['packages'][name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError: report['packages'][name] = 'not installed'
        model_path = bundle_file(args.bundle, manifest['models'][args.kind]['path'])
        arrays = {}; extra = {}
        if args.kind in ('pose','face'):
            import config as C
            from pose import PoseExtractor
            from face import FaceExtractor, NEED
            # Use the original wrappers and parameters. Shadow is disabled in the
            # subprocess so the FaceMesh smoke test cannot load a second model.
            C.YOLO_SHADOW_ENABLED = False
            if args.kind == 'pose':
                # Route only the asset directory to the verified bundle copy;
                # original model variant and every Tasks option stay unchanged.
                original_directory = C.MODELS_DIR
                C.MODELS_DIR = model_path.parent
                try:
                    extractor = PoseExtractor()
                finally:
                    C.MODELS_DIR = original_directory
            else:
                extractor = FaceExtractor(model_path=model_path)
            frames = np.load(args.bundle / 'inputs/frames.npz', allow_pickle=False)
            valid = []; values = []; point_arrays = []; point_ids = sorted(NEED)
            times = []
            for bgr, ts in zip(frames['bgr'], frames['timestamp_ms']):
                t0 = time.perf_counter(); result = extractor.detect(bgr, int(ts)); times.append((time.perf_counter()-t0)*1000)
                valid.append(result is not None)
                if args.kind == 'pose':
                    values.append(result if result is not None else np.full((33,4), np.nan, np.float32))
                else:
                    values.append([result[key] for key in ('ear','mar','pitch','yaw','roll')] if result is not None else [np.nan]*5)
                    point_arrays.append([result['P'][key] for key in point_ids] if result is not None else np.full((len(point_ids),2),np.nan))
            arrays['valid'] = np.asarray(valid, bool)
            arrays['landmarks' if args.kind == 'pose' else 'geometry'] = np.asarray(values)
            if args.kind == 'face':
                arrays.update(points=np.asarray(point_arrays), point_ids=np.asarray(point_ids))
                extra['geometry_columns'] = ['ear','mar','pitch','yaw','roll']
                extra['coverage'] = 'Original FaceExtractor exposed point subset and geometry; one Tasks FaceLandmarker'
            if not any(valid): raise ValueError('Inference ran but no detections; fixture does not prove detected-result parity')
            extra.update(valid_frames=int(sum(valid)), inference_ms=times)
        elif args.kind == 'transformer':
            import torch
            from live import load_infer_model
            torch.set_num_threads(1)
            model, _, _, classes, window = load_infer_model(model_path, device='cpu')
            tensor = np.load(args.bundle / 'inputs/transformer.npy', allow_pickle=False)
            if tensor.shape != (1,window,132) or tensor.dtype != np.float32 or not np.isfinite(tensor).all():
                raise ValueError('Frozen Transformer input must match actual checkpoint window and 132 features')
            with torch.inference_mode():
                logits = model(torch.from_numpy(tensor))
                arrays = dict(logits=logits.numpy(), probabilities=torch.softmax(logits,dim=1).numpy())
            extra.update(classes=classes, window=window)
        else:
            from yolo_runtime import OnnxClassifier, preprocess
            positive, negative = ({'open'},{'closed'}) if args.kind == 'eye' else ({'yawn'},{'no_yawn'})
            adapter = OnnxClassifier(model_path, positive, negative)
            probabilities = []; roi_probabilities = []; preprocessed = []
            for name in (('left','right') if args.kind == 'eye' else ('mouth',)):
                tensor = np.load(args.bundle / f'inputs/{name}_tensor.npy', allow_pickle=False)
                roi = np.load(args.bundle / f'inputs/{name}_roi.npy', allow_pickle=False)
                if tensor.shape != (1,3,224,224) or tensor.dtype != np.float32 or not np.isfinite(tensor).all():
                    raise ValueError('Invalid frozen YOLO tensor')
                probabilities.append(adapter.session.run(None,{adapter.session.get_inputs()[0].name:tensor})[0])
                preprocessed.append(preprocess(roi)); roi_probabilities.append(adapter(roi))
            arrays = dict(probabilities=np.asarray(probabilities), roi_probabilities=np.asarray(roi_probabilities),
                          preprocessed=np.asarray(preprocessed))
            extra.update(names=adapter.names, positive_index=adapter.index, backend=adapter.backend,
                         providers=adapter.session.get_providers())
        for name, array in arrays.items():
            # Missing detections have explicit valid masks, never normal states.
            if np.isinf(array).any(): raise ValueError(f'Infinite output: {name}')
            if args.kind not in ('pose','face') and not np.isfinite(array).all(): raise ValueError(f'Nonfinite output: {name}')
        path = args.out / f'{args.kind}.npz'
        np.savez_compressed(path, **arrays)
        report.update(passed=True, output_sha256=sha(path), arrays={k:dict(shape=list(v.shape),dtype=str(v.dtype)) for k,v in arrays.items()}, **extra)
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    report['elapsed_s'] = time.perf_counter() - start
    write_json(args.out / f'{args.kind}.json', report)
    return 0 if report['passed'] else 1


def run(args):
    verify_bundle(args.bundle)
    if args.out.exists(): raise FileExistsError('Choose a new output directory')
    args.out.mkdir(parents=True)
    results = {}
    for kind in args.only:
        try: results[kind] = bool(child(args.bundle, args.out, kind))
        except subprocess.TimeoutExpired:
            results[kind] = False
            write_json(args.out / f'{kind}.json',dict(kind=kind,passed=False,error='worker timed out',board_validation='待板端验证'))
        print(kind, 'PASS' if results[kind] else 'FAIL', flush=True)
    report = dict(schema=1, passed=all(results.values()), results=results,
                  manifest_sha256=sha(args.bundle / 'manifest.json'), board_validation='待板端验证')
    write_json(args.out / 'report.json', report)
    return 0 if report['passed'] else 1


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest='action', required=True)
    prepare_parser = sub.add_parser('prepare')
    prepare_parser.add_argument('--video', type=Path, required=True)
    prepare_parser.add_argument('--checkpoint', type=Path, required=True, help='Trusted existing Transformer .pt only')
    prepare_parser.add_argument('--out', type=Path, required=True)
    prepare_parser.add_argument('--frames', type=int, default=45)
    prepare_parser.add_argument('--start', type=float, default=1.)
    for action in ('run','_worker'):
        parser = sub.add_parser(action)
        parser.add_argument('--bundle', type=Path, required=True)
        parser.add_argument('--out', type=Path, required=True)
        if action == 'run': parser.add_argument('--only', choices=KINDS, nargs='+', default=list(KINDS))
        else: parser.add_argument('--kind', choices=KINDS, required=True)
    args = ap.parse_args()
    if args.action == 'prepare':
        if args.start < 0 or not np.isfinite(args.start) or args.frames <= 0: ap.error('Invalid frame count/start time')
        prepare(args)
    elif args.action == 'run': raise SystemExit(run(args))
    else:
        code = worker(args)
        sys.stdout.flush(); sys.stderr.flush()
        os._exit(code)  # Test worker only; reports are already closed/flushed.


if __name__ == '__main__': main()
