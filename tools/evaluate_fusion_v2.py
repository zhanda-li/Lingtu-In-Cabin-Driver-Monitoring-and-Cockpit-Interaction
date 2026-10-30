"""Replay recorded real model features; compare levels, not unlabelled accuracy."""
import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from dataclasses import asdict
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from fusion_v2 import FusionV2,FusionPolicy
import config as C

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--log',type=Path,default=ROOT/'runs/fusion_v2_yawdd.jsonl')
    args=ap.parse_args()
    recorded=[json.loads(line) for line in args.log.read_text(encoding='utf-8').splitlines()]
    if not recorded:raise RuntimeError('No recorded real decision features')
    samples=[r['input_features'] for r in recorded]
    if any(b['timestamp']<=a['timestamp'] for a,b in zip(samples,samples[1:])):
        raise ValueError('Non-monotonic log: use a fresh file per replay')
    engine=FusionV2(FusionPolicy(**C.FUSION_V2_POLICY));rows=[];fusion_ms=[]
    for sample in samples:
        started=time.perf_counter();out=engine.update(sample);fusion_ms.append((time.perf_counter()-started)*1000)
        rows.append(dict(timestamp=sample['timestamp'],legacy_level=sample['legacy_level'],fusion_v2_level=out['level'],
            final_level=sample['legacy_level'],selected_mode='legacy',
            eye_level=out['eye_evidence']['level'],mouth_level=out['mouth_evidence']['level'],
            head_level=out['head_evidence']['level'],transformer_level=out['transformer_evidence']['level'],
            face_level=out['face_evidence']['level'],lr_warmup=out['face_evidence']['warmup'],
            lr_valid=out['face_evidence']['valid'],conflicts='|'.join(out['conflicts']),
            degraded=out['degraded'],level_change_reason='原版等级保留；具体来源见原始 Legacy CSV',
            v2_level_change_reason=out['level_change_reason']))
    folder=ROOT/'docs/validation';folder.mkdir(parents=True,exist_ok=True)
    with (folder/'fusion_v2_yawdd.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=rows[0].keys());writer.writeheader();writer.writerows(rows)
    tests=[]
    for script in ['test_yolo_shadow.py','test_fusion_v2.py']:
        result=subprocess.run([sys.executable,str(ROOT/'tools'/script)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
        (ROOT/'runs'/f'fusion_{script}.txt').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
        tests.append(dict(script=script,exit_code=result.returncode))
    duration=rows[-1]['timestamp']-rows[0]['timestamp']
    def transitions(key):return sum(a[key]!=b[key] for a,b in zip(rows,rows[1:]))
    report=dict(basic_acceptance_passed=all(t['exit_code']==0 for t in tests),
        policy_source_sha256=hashlib.sha256((ROOT/'src/fusion_v2.py').read_bytes()).hexdigest(),
        policy=asdict(engine.policy),
        source='YawDD first public participant; recorded real Pose/FaceMesh/YOLO/LR decision features',
        inference_log=str(args.log),decisions=len(rows),duration_seconds=duration,
        levels_legacy=dict(Counter(r['legacy_level'] for r in rows)),levels_v2=dict(Counter(r['fusion_v2_level'] for r in rows)),
        level_disagreements=sum(r['legacy_level']!=r['fusion_v2_level'] for r in rows),
        legacy_transitions=transitions('legacy_level'),v2_transitions=transitions('fusion_v2_level'),
        lr_valid_decisions=sum(r['lr_valid'] for r in rows),conflict_decisions=sum(bool(r['conflicts']) for r in rows),
        false_positive_rate=None,false_negative_rate=None,detection_delay=None,
        metrics_unavailable_reason='No reliable frame/event labels; disagreement is not error or improvement.',
        tests=tests,scope='Basic implementation checks only, not calibrated superiority or production acceptance')
    import numpy as np
    report['fusion_rules_ms_median']=float(np.median(fusion_ms))
    report['fusion_rules_ms_p95']=float(np.percentile(fusion_ms,95))
    (folder/'fusion_v2_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not report['basic_acceptance_passed']:raise SystemExit(1)

if __name__=='__main__':main()
