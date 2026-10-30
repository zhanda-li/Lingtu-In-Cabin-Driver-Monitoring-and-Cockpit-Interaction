"""Reuse original video comparator to check Legacy while V2 computes alongside."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from cmp_cam_fuse import rows,COLS,check_header
ROOT=Path(__file__).resolve().parents[1]

def main():
    results=[]
    token=str(time.time_ns())
    for name in ['normal','fatigue']:
        clip=ROOT/f'data/raw/{name}/{name}_00.mp4'
        outputs=[]
        for tag,script in [('reference','src/fuse.py'),('parallel','ui/cam.py')]:
            output=ROOT/f'runs/fusion_regress_{token}_{name}_{tag}.csv';outputs.append(output)
            env=dict(os.environ,FUSION_MODE='legacy',DMS_FUSION_COMPARE='1',DMS_FUSION_V2_ALLOWED='0',
                     DMS_YOLO_SHADOW='1' if tag=='parallel' else '0',DMS_YOLO_BACKEND='onnx',DMS_YOLO_ASYNC='0',
                     DMS_FUSION_LOG=str(ROOT/f'runs/fusion_regress_{token}_{name}.jsonl'),
                     OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
            command=[sys.executable,str(ROOT/script),'--replay',str(clip),'--fast']
            command+=['--no-display','--no-voice','--quiet','--log-probs',str(output)] if tag=='reference' else ['--no-overlay','--dump',str(output)]
            result=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=240)
            (ROOT/f'runs/fusion_regress_{token}_{name}_{tag}.txt').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
            if result.returncode:raise RuntimeError(f'{script} failed: {result.stderr[-500:]}')
        a,b=map(rows,outputs)
        error=check_header(*outputs,a,b)
        if error:raise RuntimeError(error)
        if not a or len(a)!=len(b):raise RuntimeError('Decision row mismatch')
        differences={k:sum(x[k]!=y[k] for x,y in zip(a,b)) for k in COLS}
        results.append(dict(clip=str(clip),rows=len(a),differences=differences,passed=not any(differences.values())))
        print(name,results[-1]['passed'],len(a),flush=True)
    report=dict(all_passed=all(r['passed'] for r in results),total_rows=sum(r['rows'] for r in results),results=results,
                note='Original local regression clips only; not public-data accuracy. Real model inference in both processes, with OMP/MKL thread counts fixed to 1 equally.')
    (ROOT/'docs/validation/legacy_regression.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    if not report['all_passed']:raise SystemExit(1)

if __name__=='__main__':main()
