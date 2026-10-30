"""Local HTTP/WebSocket integration check with external services disabled."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
import aiohttp
import argparse
ROOT = Path(__file__).resolve().parents[1]

async def mode_check(ws,allowed):
    results=[]
    for target in (['v2','legacy','bad'] if allowed else ['v2','bad']):
        await ws.send_json({'type':'fusion_mode','mode':target})
        deadline=time.monotonic()+20
        ack=None;effective=None
        expected=allowed and target!='bad'
        while time.monotonic()<deadline:
            message=await ws.receive_json()
            if message.get('type')=='fusion_mode':
                ack=message['data'];assert ack['ok']==expected
                if not expected:break
            if ack and message.get('type')=='state':
                state=message['data'];fusion=state.get('fusion_v2',{})
                if fusion.get('mode')==target:
                    assert fusion['final_level']==state['l_fused']
                    if target=='v2':assert fusion['fusion_v2_level']==state['l_fused']
                    effective=target;break
        assert ack is not None and (not expected or effective==target),'Missing backend mode acknowledgment/application'
        results.append(dict(target=target,ack=ack,effective=effective))
    return results

async def probe(enabled,allow_switch=None):
    config = ROOT/'runs/yolo_ws_test_config.json'
    config.write_text(json.dumps(dict(agent={'backend':'scripted'},
        asr={'enabled':False,'preload':False},tts={'enabled':False},
        serial_hr={'enabled':False},wechat={'enabled':False},amap={'enabled':False})),encoding='utf-8')
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0))
        port = reservation.getsockname()[1]
    env = dict(os.environ,DMS_YOLO_SHADOW='1' if enabled else '0',
               DMS_YOLO_BACKEND='onnx',DMS_YOLO_ASYNC='1',DMS_YOLO_LOG='')
    env.update(FUSION_MODE='legacy',DMS_FUSION_COMPARE='1' if allow_switch is not None else '0',
               DMS_FUSION_V2_ALLOWED='1' if allow_switch else '0',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
    log = ROOT/f'runs/yolo_ws_{int(enabled)}.txt'
    command = [sys.executable,str(ROOT/'ui/server.py'),'--config',str(config),
        '--source','cam:datasets/yawdd_samples/01-FemaleNoGlasses.avi',
        '--host','127.0.0.1','--port',str(port)]
    with log.open('w',encoding='utf-8') as output:
        child = subprocess.Popen(command,cwd=ROOT,env=env,stdout=output,stderr=subprocess.STDOUT,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        started = time.monotonic()
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as session:
                while time.monotonic()-started<60:
                    if child.poll() is not None:
                        raise RuntimeError(f'UI server exited; inspect {log}')
                    try:
                        async with session.get(f'http://127.0.0.1:{port}/') as response:
                            if response.status==200:
                                break
                    except (aiohttp.ClientError,asyncio.TimeoutError):
                        pass
                    await asyncio.sleep(.5)
                else:
                    raise TimeoutError('UI server startup timeout')
                async with session.get(f'http://127.0.0.1:{port}/index.html') as response:
                    assert response.status==200
                async with session.ws_connect(f'http://127.0.0.1:{port}/ws',receive_timeout=15) as ws:
                    for _ in range(150):
                        message = await ws.receive_json()
                        if message.get('type')!='state':
                            continue
                        state = message['data']
                        assert all(k in state for k in ['l_fused','l1','l2','probs','severity'])
                        if not enabled:
                            assert 'yolo_shadow' not in state
                            return dict(enabled=False,legacy_keys=sorted(state),shadow_present=False)
                        shadow = state.get('yolo_shadow')
                        if shadow and 'inference_ms' in shadow and not shadow.get('pending'):
                            assert shadow['mode']=='shadow'
                            for key in ['eye_left_open_prob','eye_right_open_prob','yawn_probability']:
                                assert shadow[key] is None or 0<=shadow[key]<=1
                            assert 'fusion_v2' in state and 'yolo' in state
                            result=dict(enabled=True,legacy_keys=sorted(k for k in state if k not in ('yolo_shadow','fusion_v2','yolo')),
                                        shadow_present=True,eye_backend=shadow['eye_backend'],
                                        sample_timestamp=shadow['sample_timestamp'])
                            if allow_switch is not None:
                                result['mode_checks']=await mode_check(ws,allow_switch)
                            return result
                    raise RuntimeError('No completed shadow result reached WebSocket')
        finally:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(timeout=5)

async def main():
    ap=argparse.ArgumentParser();ap.add_argument('--fusion-tests',action='store_true');args=ap.parse_args()
    if args.fusion_tests:
        denied=await probe(True,False)
        allowed=await probe(True,True)
        report=dict(denied=denied,allowed=allowed,note='Real backend confirmations and selected decision states, no simulated mode labels')
        (ROOT/'docs/validation/fusion_websocket.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2));return
    off = await probe(False)
    on = await probe(True)
    assert off['legacy_keys']==on['legacy_keys']
    report = dict(http_cover_and_index='200 in both runs',off=off,on=on,
                  note='Real localhost aiohttp server and WS. No browser rendering, external services or hardware used.')
    (ROOT/'docs/yolo_websocket_check.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__ == '__main__':
    asyncio.run(main())
