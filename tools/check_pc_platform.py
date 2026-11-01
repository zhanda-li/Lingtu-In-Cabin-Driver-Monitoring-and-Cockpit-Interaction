"""Opt-in PC camera and Windows SAPI smoke check, no images/audio recorded."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--camera', action='store_true')
    ap.add_argument('--voice', action='store_true')
    args = ap.parse_args()
    result = dict(platform=sys.platform, linux_hardware_tested=False)
    if args.camera:
        from live import CameraSource
        src = None
        try:
            src = CameraSource()
            deadline = time.monotonic() + 8
            frame, ok = None, False
            while time.monotonic() < deadline:
                frame, ok = src.read()
                if ok:
                    break
            result['camera'] = dict(ok=ok, backend=src.cap.getBackendName(),
                                    shape=list(frame.shape) if ok else None,
                                    media_time=src.media_time())
        except Exception as exc:
            result['camera'] = dict(ok=False, error=f'{type(exc).__name__}: {exc}')
        finally:
            if src is not None:
                src.release()
    if args.voice:
        if sys.platform != 'win32':
            result['voice'] = dict(ok=False, error='This smoke check exercises Windows SAPI only')
        else:
            from ui.tts import ServerVoice
            voice = ServerVoice({'enabled': False})
            voice._sapi_once('灵途智行，兼容性测试。', 'normal')
            result['voice'] = dict(ok=voice.spoken == 1, status=voice.status(),
                                   audible_confirmed_by_user=False)
    path = ROOT / 'runs/compat_pc_hardware.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True, indent=2))
    if any(not value.get('ok') for value in result.values() if isinstance(value, dict)):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
