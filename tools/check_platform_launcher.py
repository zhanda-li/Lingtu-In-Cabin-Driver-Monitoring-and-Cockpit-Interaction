"""Exercise the Linux launcher in Bash with a recording stub, not a DMS server."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bash', default='bash')
    args = ap.parse_args()
    subprocess.run([args.bash, '-n', 'ui/run_ui.sh'], cwd=ROOT, check=True)
    results = []
    with tempfile.TemporaryDirectory(prefix='compat_launcher_', dir=ROOT / 'runs') as temp:
        directory = Path(temp)
        recorder = directory / 'record.py'
        recorder.write_text(
            "import json,os,sys\nfrom pathlib import Path\n"
            "keys=['FUSION_MODE','DMS_YOLO_SHADOW','DMS_FUSION_COMPARE','DMS_FUSION_V2_ALLOWED','DMS_CAMERA_DEVICE']\n"
            "Path(os.environ['DMS_STUB_RECORD']).write_text(json.dumps(dict(args=sys.argv[1:],env={k:os.environ.get(k) for k in keys})))\n"
            "print('launcher stub: no server or hardware started')\n"
            "sys.exit(int(os.environ.get('DMS_STUB_EXIT','0')))\n", encoding='utf-8')
        stub = directory / 'python-stub.sh'
        # Shell single-quote escaping for executable paths; no arbitrary shell args.
        quote = lambda value: "'" + str(value).replace("'", "'\"'\"'") + "'"
        stub.write_text('#!/usr/bin/env bash\nexec ' + quote(Path(sys.executable).as_posix()) +
                        ' ' + quote(recorder.as_posix()) + ' "$@"\n', encoding='utf-8', newline='\n')
        stub.chmod(0o700)
        for mode, expected in [('legacy', ['legacy','0','0','0']),
                               ('shadow', ['legacy','1','1','0']), ('v2', ['v2','1','1','1'])]:
            output = directory / (mode + '.json')
            log = directory / (mode + '.log')
            env = dict(os.environ, DMS_PYTHON=stub.as_posix(), DMS_UI_LOG=log.as_posix(),
                       DMS_STUB_RECORD=output.as_posix(), DMS_CAMERA_DEVICE='/dev/video2')
            # Git Bash otherwise rewrites /dev/video2 when spawning native
            # Windows Python. This is a host test setting, not a Linux fix.
            env['MSYS2_ENV_CONV_EXCL'] = 'DMS_CAMERA_DEVICE'
            proc = subprocess.run([args.bash, 'ui/run_ui.sh', '--mode', mode, '--port', '9876'],
                                  cwd=ROOT, env=env, capture_output=True, timeout=20)
            assert proc.returncode == 0, proc.stderr
            record = json.loads(output.read_text())
            assert list(record['env'].values()) == expected + ['/dev/video2'], record
            assert record['args'] == ['-u','ui/server.py','--source','cam','--port','9876'], record
            assert 'launcher stub' in log.read_text()
            results.append(dict(mode=mode, passed=True, observed=record))
        env['DMS_STUB_EXIT'] = '7'
        failed = subprocess.run([args.bash, 'ui/run_ui.sh', '--mode', 'v2'], cwd=ROOT, env=env,
                                capture_output=True, timeout=20)
        assert failed.returncode == 7, failed.returncode
        invalid = subprocess.run([args.bash, 'ui/run_ui.sh', '--mode', 'bad'], cwd=ROOT, env=env,
                                 capture_output=True, timeout=20)
        assert invalid.returncode == 2
    report = dict(bash=args.bash, syntax_passed=True, modes=results,
                  failure_exit_preserved=True, invalid_mode_rejected=True,
                  note='Bash + recording stub; not Linux DMS/ARM64 execution')
    (ROOT / 'runs/compat_launcher.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
