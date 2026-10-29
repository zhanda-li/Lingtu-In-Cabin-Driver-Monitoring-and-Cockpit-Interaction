"""Participant-separated qualitative smoke test; no accuracy or frame label claims."""
import sys
import json
from pathlib import Path
import cv2
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from face_roi_yolo import Classifier

model = Classifier(ROOT/'models/yolo_shadow/best.pt', {'open'}, {'closed'})
data = ROOT/'datasets/mrlEyes_2018_01'
participants = sorted({p.parent for p in data.rglob('*.png')})
report = {'kind': 'qualitative_smoke_only', 'split': 'first and last participant; no training', 'samples': []}
for participant in participants[:1] + participants[-1:]:
    images = sorted(participant.glob('*.png'))
    step = max(1, len(images)//10)
    for path in images[::step][:10]:
        image = cv2.imread(str(path))
        if image is not None:
            report['samples'].append(dict(file=str(path.relative_to(data)), open_probability=model(image)))
if not report['samples']:
    raise RuntimeError('No readable MRL samples')
print(json.dumps(report, indent=2))
