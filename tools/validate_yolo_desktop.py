"""Reproducible desktop acceptance runner. No training or board access."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--full',action='store_true',help='Also run local HTTP/WS and bounded full-CamSource resource profiles')
    args = ap.parse_args()
    cases = [('weight_hashes','download_yolo_shadow.py',[]),
             ('unit_and_original_fusion','test_yolo_shadow.py',[]),
             ('real_model_loading_cpu','check_yolo_shadow.py',[]),
             ('labelled_mrl','evaluate_yolo_mrl.py',[]),
             ('public_yawdd','validate_yolo_video.py',['datasets/yawdd_samples/01-FemaleNoGlasses.avi']),
             ('mouth_qualitative_review','review_yolo_mouth.py',[])]
    if args.full:
        cases += [('http_websocket','check_yolo_websocket.py',[]),
                  ('full_camera_resources','profile_yolo_desktop.py',[])]
    env = dict(os.environ,DMS_YOLO_BACKEND='onnx',DMS_YOLO_SHADOW='0',DMS_YOLO_LOG='')
    results = []
    for name,script,extra in cases:
        command = [sys.executable,str(ROOT/'tools'/script),*extra]
        case_env = dict(env,DMS_YOLO_BACKEND='pt') if name=='real_model_loading_cpu' else env
        started = time.monotonic()
        result = subprocess.run(command,cwd=ROOT,env=case_env,capture_output=True,text=True,
                                encoding='utf-8',errors='replace',timeout=240)
        log = ROOT/f'runs/yolo_accept_{name}.txt'
        log.write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
        results.append(dict(case=name,exit_code=result.returncode,
                            seconds=time.monotonic()-started,log=str(log.relative_to(ROOT))))
        print(name,'PASS' if result.returncode==0 else 'FAIL',flush=True)
        if result.returncode != 0:
            break
    source = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
              for p in [ROOT/'src/face_roi_yolo.py',ROOT/'src/yolo_runtime.py',ROOT/'src/face.py',ROOT/'ui/state.py',ROOT/'ui/cam.py']}
    passed = len(results)==len(cases) and all(r['exit_code']==0 for r in results)
    report = dict(all_passed=passed,full=args.full,source_sha256=source,cases=results,
        limits=['No RK3568 device used','No reliable speech/laughter/singing frame labels',
                'No NITYMED access','MRL upstream training overlap unknown',
                'Fusion L0-L3 combination test is a source-code regression, not natural-video coverage of every level'])
    (ROOT/'docs/yolo_desktop_acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    raise SystemExit(0 if passed else 1)

if __name__ == '__main__':
    main()
