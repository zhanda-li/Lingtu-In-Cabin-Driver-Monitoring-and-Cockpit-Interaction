"""Inspect real weights and benchmark CPU; synthetic input is NOT accuracy validation."""
import sys
import json
import hashlib
import time
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from face_roi_yolo import FaceRoiYolo
import ultralytics

def main():
    report = {'ultralytics': ultralytics.__version__, 'models': []}
    detector = FaceRoiYolo(ROOT/'models/yolo_shadow/best.pt', ROOT/'models/yolo_shadow/best_yawn.pt')
    for adapter in [detector.eye, detector.mouth]:
        model = adapter.model
        path = Path(model.ckpt_path)
        roi = np.full((96, 96, 3), 127, np.uint8)
        adapter(roi)
        ms = []
        for _ in range(10):
            start = time.perf_counter(); p = adapter(roi)
            ms.append((time.perf_counter()-start)*1000)
        report['models'].append(dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            task=model.task, names=model.names, training_args=model.ckpt.get('train_args'),
            inference_imgsz=adapter.imgsz, synthetic_probability=p,
            cpu_ms_median=float(np.median(ms)), cpu_ms_p95=float(np.percentile(ms,95))))
    print(json.dumps(report, indent=2, default=str))

if __name__ == '__main__':
    main()
