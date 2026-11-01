"""Compare isolated frozen-input model outputs. Never compare fatigue accuracy."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

from portability_models import sha, KINDS, write_json


def compare_arrays(reference, candidate, atol, rtol):
    if reference.shape != candidate.shape or reference.dtype != candidate.dtype:
        return dict(passed=False, reason='shape/dtype mismatch')
    if np.isinf(reference).any() or np.isinf(candidate).any():
        return dict(passed=False, reason='infinite output')
    if reference.dtype.kind in 'biu':
        return dict(passed=bool(np.array_equal(reference,candidate)), exact=True)
    if not np.array_equal(np.isnan(reference),np.isnan(candidate)):
        return dict(passed=False, reason='missing/nonfinite pattern differs')
    finite = np.isfinite(reference)
    # Matching absence is reported explicitly, never treated as normal evidence.
    if not finite.any(): return dict(passed=False, reason='no finite numerical evidence')
    left, right = reference[finite].astype(np.float64), candidate[finite].astype(np.float64)
    delta = np.abs(left-right)
    return dict(passed=bool(np.allclose(left,right,atol=atol,rtol=rtol)),
                max_abs=float(delta.max(initial=0)), mean_abs=float(delta.mean()),
                max_relative=float(np.max(delta/np.maximum(np.abs(left),1e-12),initial=0)),
                finite_values=int(finite.sum()), missing_values=int((~finite).sum()))


def compare(reference, candidate, tolerance):
    overall = True; results = {}
    summaries = [json.loads((p/'report.json').read_text(encoding='utf-8')) for p in (reference,candidate)]
    if not all(r.get('passed') is True for r in summaries):
        raise ValueError('Both model runs must pass before comparison')
    if summaries[0]['manifest_sha256'] != summaries[1]['manifest_sha256']:
        raise ValueError('Input/model manifest SHA256 differs')
    kinds = set(summaries[0]['results'])
    if not kinds or kinds != set(summaries[1]['results']) or not kinds.issubset(KINDS):
        raise ValueError('Model run coverage differs or is empty')
    for kind in sorted(kinds):
        reports = [json.loads((p/f'{kind}.json').read_text(encoding='utf-8')) for p in (reference,candidate)]
        paths = [p/f'{kind}.npz' for p in (reference,candidate)]
        for report, path in zip(reports, paths):
            if report.get('passed') is not True or sha(path) != report.get('output_sha256'):
                raise ValueError(f'Failed/corrupt model output: {kind}')
        for key in ('manifest_sha256','model_sha256','classes','names','positive_index','geometry_columns','window'):
            if reports[0].get(key) != reports[1].get(key):
                raise ValueError(f'{kind} semantic identity differs: {key}')
        if reports[0].get('device') != 'cpu' or reports[1].get('device') != 'cpu':
            raise ValueError('This comparison profile is CPU-only')
        policy = tolerance[kind]; arrays = {}
        with np.load(paths[0],allow_pickle=False) as left, np.load(paths[1],allow_pickle=False) as right:
            if not left.files or set(left.files) != set(right.files): raise ValueError('Output array names differ')
            for name in left.files:
                arrays[name] = compare_arrays(left[name],right[name],**policy)
            if 'probabilities' in left.files:
                arrays['top1_agreement'] = dict(passed=bool(np.array_equal(np.argmax(left['probabilities'],axis=-1),
                                                                          np.argmax(right['probabilities'],axis=-1))))
        passed = all(row['passed'] for row in arrays.values())
        results[kind] = dict(passed=passed, tolerance=policy, arrays=arrays,
                             reference_packages=reports[0].get('packages'),candidate_packages=reports[1].get('packages'))
        overall &= passed
    return dict(schema=1, passed=bool(overall), results=results, board_validation='待板端验证',
                limits=['Engineering numerical tolerances only; not calibrated fatigue decision thresholds',
                        'Matching values do not establish detection accuracy, sensitivity or clinical performance',
                        'A PC self-comparison is only a harness check, never ARM64 parity'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('reference', type=Path); ap.add_argument('candidate',type=Path)
    ap.add_argument('--tolerances',type=Path,default=Path(__file__).with_name('portability_tolerances.json'))
    ap.add_argument('--out',type=Path,required=True)
    args = ap.parse_args()
    try:
        policy = json.loads(args.tolerances.read_text(encoding='utf-8'))
        for kind in KINDS:
            for name in ('atol','rtol'):
                value=policy[kind][name]
                if not isinstance(value,(int,float)) or not np.isfinite(value) or value < 0:
                    raise ValueError('Numerical tolerances must be finite and nonnegative')
        report = compare(args.reference,args.candidate,policy)
    except Exception as exc:
        report = dict(passed=False,error=f'{type(exc).__name__}: {exc}',board_validation='待板端验证')
    args.out.parent.mkdir(parents=True,exist_ok=True)
    write_json(args.out,report)
    print(json.dumps(dict(passed=report['passed'],output=str(args.out))))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__': main()
