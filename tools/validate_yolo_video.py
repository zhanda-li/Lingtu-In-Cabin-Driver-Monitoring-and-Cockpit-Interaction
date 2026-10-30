"""Qualitative public-video replay using one existing FaceMesh; no accuracy claims."""
import argparse
import json
import os
import sys
import time
from pathlib import Path
import cv2
import numpy as np
import psutil
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT))
import config as C
C.YOLO_SHADOW_ENABLED = False
from face import FaceExtractor
from face_roi_yolo import FaceRoiYolo

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('video', type=Path)
    ap.add_argument('--output', type=Path, default=ROOT/'docs/yawdd_shadow_replay.json')
    ap.add_argument('--hz', type=float, default=5)
    ap.add_argument('--max-frames', type=int, default=1000)
    args = ap.parse_args()
    if args.hz <= 2 or args.max_frames < 1:
        ap.error('hz must exceed 2 to preserve temporal gap semantics')
    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        ap.error('Video cannot be opened')
    fps = capture.get(cv2.CAP_PROP_FPS)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if fps <= 0:
        ap.error('Invalid video frame rate')
    stride = max(1,int(round(fps/args.hz)))
    face = FaceExtractor(running_mode='VIDEO')
    yolo = FaceRoiYolo(C.YOLO_EYE_PATH,C.YOLO_MOUTH_PATH)
    process = psutil.Process()
    cpu0 = process.cpu_times()
    started = time.perf_counter()
    rows, latency, rss = [], [], []
    index = 0
    while len(rows) < args.max_frames:
        ok, image = capture.read()
        if not ok:
            break
        if index % stride == 0:
            timestamp = index/fps
            t0 = time.perf_counter()
            d = face.detect(image,timestamp*1000)
            out = yolo.process(image,d['P'] if d else None,d['mar'] if d else None,timestamp)
            out.update(timestamp=timestamp,face_present=d is not None)
            out['mar'] = float(d['mar']) if d is not None and np.isfinite(d['mar']) else None
            rows.append(out)
            latency.append((time.perf_counter()-t0)*1000)
            rss.append(process.memory_info().rss)
        index += 1
    capture.release()
    wall = time.perf_counter()-started
    cpu1 = process.cpu_times()
    report = dict(video=str(args.video),mode='qualitative_only_no_frame_labels',
        backend=os.environ.get('DMS_YOLO_BACKEND','pt'),source_fps=fps,sample_stride=stride,
        processed_frames=len(rows),face_present=sum(r['face_present'] for r in rows),
        max_frames=args.max_frames,source_frame_count=frame_count,
        decode_reached_end=(index>=frame_count) if frame_count>0 else None,
        wall_seconds=wall,peak_sampled_rss_mb=max(rss,default=0)/1024**2,
        cpu_core_equivalents=(cpu1.user+cpu1.system-cpu0.user-cpu0.system)/max(wall,1e-6),
        face_plus_yolo_ms_median=float(np.median(latency)) if latency else None,
        face_plus_yolo_ms_p95=float(np.percentile(latency,95)) if latency else None,
        note='One participant/video; no train/test accuracy. CPU/RSS are this validation process only.',rows=rows)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},indent=2),flush=True)
    # Match project CLI lifecycle: MediaPipe destructor can stall on Windows.
    os._exit(0)

if __name__ == '__main__':
    main()
