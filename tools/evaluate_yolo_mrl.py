"""Labelled MRL evaluation by subject; upstream training overlap is unknown."""
import json
import sys
from pathlib import Path
import cv2
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from yolo_runtime import OnnxClassifier

def main():
    data = ROOT/'datasets/mrlEyes_2018_01/mrlEyes_2018_01'
    annotation = (data/'annotation.txt').read_text()
    if '0 - close' not in annotation or '1 - open' not in annotation:
        raise ValueError('Unexpected dataset label specification')
    participants = sorted(p for p in data.iterdir() if p.is_dir() and p.name.startswith('s'))
    if len(participants) < 5:
        raise ValueError('Need at least five participants for separated evaluation partition')
    evaluation = participants[-4:]
    model = OnnxClassifier(ROOT/'models/yolo_shadow/best.onnx',{'open'},{'closed'})
    rows = []
    for participant in evaluation:
        groups = {0:[],1:[]}
        for path in sorted(participant.glob('*.png')):
            tokens = path.stem.split('_')
            if len(tokens) != 8 or tokens[4] not in ('0','1'):
                raise ValueError(f'Invalid annotation filename {path.name}')
            groups[int(tokens[4])].append(path)
        for label,paths in groups.items():
            # Spread samples through each subject/state sequence, never split neighbors.
            indices = np.linspace(0,len(paths)-1,min(50,len(paths)),dtype=int) if paths else []
            for index in indices:
                path = paths[index]
                image = cv2.imread(str(path))
                if image is None:
                    raise ValueError(f'Unreadable image {path}')
                prob = model(image)
                rows.append(dict(subject=participant.name,file=path.name,label=label,
                                 open_probability=prob,predicted=int(prob>=.5)))
    confusion = [[sum(r['label']==a and r['predicted']==b for r in rows) for b in [0,1]] for a in [0,1]]
    report = dict(dataset='MRL',label_source='Bundled annotation.txt; filename token index 4',
        class_order=['closed','open'],threshold=.5,evaluation_subjects=[p.name for p in evaluation],
        excluded_subjects=[p.name for p in participants[:-4]],sample_count=len(rows),
        selection='Up to 50 evenly spaced images per subject per eye-state class; no training or tuning',
        confusion_matrix_rows_true_cols_pred=confusion,
        accuracy=sum(r['label']==r['predicted'] for r in rows)/len(rows),
        limitation='Upstream checkpoint training provenance unknown; overlap cannot be ruled out. Balanced subset is not full MRL or end-to-end ROI accuracy.',
        rows=rows)
    (ROOT/'docs/yolo_mrl_labelled_eval.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('rows','excluded_subjects')},indent=2))

if __name__ == '__main__':
    main()
