"""Summarize only freshly generated regression files; do not upload user video/logs."""
import csv
import argparse
import json
from pathlib import Path
import numpy as np
from cmp_cam_fuse import COLS
ROOT = Path(__file__).resolve().parents[1]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag',default='')
    ap.add_argument('--clip',default='normal_00.mp4')
    args = ap.parse_args()
    tag = args.tag+'_' if args.tag else ''
    paths = [ROOT/f'runs/yolo_regress_{tag}fuse.csv',ROOT/f'runs/yolo_regress_{tag}cam.csv']
    tables = []
    for path in paths:
        with path.open(encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if not set(COLS).issubset(reader.fieldnames):
                raise ValueError(f'Missing regression fields: {path}')
            tables.append(list(reader))
    a,b = tables
    assert a and len(a)==len(b), 'Empty or mismatched row counts'
    diff = {key:sum(x[key]!=y[key] for x,y in zip(a,b)) for key in COLS}
    logs = [json.loads(line) for line in (ROOT/f'runs/yolo_cam_{tag}enabled.jsonl').read_text(encoding='utf-8').splitlines()]
    timings = [r['inference_ms'] for r in logs if 'inference_ms' in r]
    report = dict(clip=args.clip,baseline='fuse.py with YOLO disabled',
        compared='ui/cam.py with ONNX shadow enabled, async bounded queue',
        decision_rows=len(a),compared_columns=COLS,different_cells_by_column=diff,
        all_equal=not any(diff.values()),levels_observed=sorted({r['l_fused'] for r in a}),
        face_lr_probability_rows=sum(r['p_fat']!='-' for r in a),
        shadow_completed_samples=len(timings),
        shadow_inference_ms_median=float(np.median(timings)),
        shadow_inference_ms_p95=float(np.percentile(timings,95)),
        limitation='Single local clip. Observed levels and LR availability reported explicitly; not full L0-L3 coverage.')
    (ROOT/f'docs/yolo_{tag}runtime_regression.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    assert report['all_equal']

if __name__ == '__main__':
    main()
