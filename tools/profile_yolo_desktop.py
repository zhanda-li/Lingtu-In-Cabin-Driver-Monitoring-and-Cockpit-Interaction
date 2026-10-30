"""Bounded desktop full-camera-source CPU/RSS profiling on public YawDD replay."""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path
import psutil
ROOT = Path(__file__).resolve().parents[1]

def run(mode, seconds):
    dump = ROOT/f'runs/yolo_profile_{mode}.csv'
    log = ROOT/f'runs/yolo_profile_{mode}.txt'
    video = ROOT/'datasets/yawdd_samples/01-FemaleNoGlasses.avi'
    env = dict(os.environ,DMS_YOLO_SHADOW='0' if mode=='off' else '1',
               DMS_YOLO_BACKEND='onnx',DMS_YOLO_ASYNC='1',DMS_YOLO_LOG='')
    command = [sys.executable,str(ROOT/'ui/cam.py'),'--replay',str(video),'--fast',
               '--no-overlay','--seconds',str(seconds),'--dump',str(dump)]
    samples = []
    with log.open('w',encoding='utf-8') as output:
        child = subprocess.Popen(command,cwd=ROOT,env=env,stdout=output,stderr=subprocess.STDOUT)
        process = psutil.Process(child.pid)
        started = time.monotonic()
        try:
            while child.poll() is None:
                if time.monotonic()-started > seconds+60:
                    raise TimeoutError('Desktop profile child exceeded bounded runtime')
                try:
                    cpu = process.cpu_times()
                    samples.append(dict(elapsed=time.monotonic()-started,
                        rss_mb=process.memory_info().rss/1024**2,cpu_seconds=cpu.user+cpu.system))
                except psutil.NoSuchProcess:
                    break
                time.sleep(.25)
            code = child.wait(timeout=5)
        finally:
            if child.poll() is None:
                child.kill(); child.wait(timeout=10)
    text = log.read_text(encoding='utf-8',errors='replace')
    if code != 0 or 'Traceback' in text or '共 ' not in text:
        raise RuntimeError(f'{mode} camera source failed; inspect {log}')
    with dump.open(encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise RuntimeError(f'No camera-source decisions for {mode}')
    warm = [s for s in samples if s['elapsed']>=10]
    cores = ((warm[-1]['cpu_seconds']-warm[0]['cpu_seconds'])/
             (warm[-1]['elapsed']-warm[0]['elapsed'])) if len(warm)>1 else None
    return dict(mode=mode,wall_seconds=time.monotonic()-started,
        peak_rss_mb=max(s['rss_mb'] for s in samples),
        mean_warm_cpu_core_equivalents=cores,warmup_excluded_seconds=10,
        decision_rows=len(rows),last_video_timestamp=float(rows[-1]['t']),
        levels_observed=sorted({r['l_fused'] for r in rows}),
        face_lr_probability_rows=sum(r['p_fat']!='-' for r in rows),exit_code=code)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds',type=float,default=30)
    args = ap.parse_args()
    if args.seconds<15:
        ap.error('At least 15 seconds required for warm CPU measurement')
    results = []
    for mode in ['off','onnx_async']:
        result = run(mode,args.seconds)
        results.append(result)
        print(json.dumps(result),flush=True)
    report = dict(workload='Public YawDD first participant replay, fast mode, no overlay',
        scope='Full CamSource: decode, Pose Transformer, FaceMesh, fusion, JPEG. HTTP server/browser excluded.',
        note='Sequential bounded wall-time profiles process different amounts of source video. Not a speedup benchmark or decision-equivalence comparison; CPU cores can exceed 1.',
        results=results)
    (ROOT/'docs/yolo_desktop_resources.json').write_text(json.dumps(report,indent=2),encoding='utf-8')

if __name__ == '__main__':
    main()
