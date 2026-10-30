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
ROOT = Path(__file__).resolve().parents[1]

async def probe(enabled):
    config = ROOT/'runs/yolo_ws_test_config.json'
    config.write_text(json.dumps(dict(agent={'backend':'scripted'},
        asr={'enabled':False,'preload':False},tts={'enabled':False},
        serial_hr={'enabled':False},wechat={'enabled':False},amap={'enabled':False})),encoding='utf-8')
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0))
        port = reservation.getsockname()[1]
    env = dict(os.environ,DMS_YOLO_SHADOW='1' if enabled else '0',
               DMS_YOLO_BACKEND='onnx',DMS_YOLO_ASYNC='1',DMS_YOLO_LOG='')
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
                            return dict(enabled=True,legacy_keys=sorted(k for k in state if k!='yolo_shadow'),
                                        shadow_present=True,eye_backend=shadow['eye_backend'],
                                        sample_timestamp=shadow['sample_timestamp'])
                    raise RuntimeError('No completed shadow result reached WebSocket')
        finally:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(timeout=5)

async def main():
    off = await probe(False)
    on = await probe(True)
    assert off['legacy_keys']==on['legacy_keys']
    report = dict(http_cover_and_index='200 in both runs',off=off,on=on,
                  note='Real localhost aiohttp server and WS. No browser rendering, external services or hardware used.')
    (ROOT/'docs/yolo_websocket_check.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__ == '__main__':
    asyncio.run(main())
