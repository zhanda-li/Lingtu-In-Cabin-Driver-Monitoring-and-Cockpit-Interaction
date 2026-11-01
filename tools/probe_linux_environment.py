"""Read-only host inventory. Default never opens devices; never writes sysfs.

Default output is stdout. --out writes only the requested report file. Optional
--probe-tools runs bounded informational commands, never installs or changes state.
"""
import argparse
import glob
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys


def read(path):
    try:
        return Path(path).read_text(errors='replace').strip()[:16000]
    except (OSError, ValueError) as exc:
        return {'unavailable': f'{type(exc).__name__}: {exc}'}


def command(argv):
    if shutil.which(argv[0]) is None:
        return {'available': False, 'reason': 'command not found'}
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, errors='replace', timeout=5)
        return dict(available=True, exit_code=proc.returncode, stdout=proc.stdout[:16000], stderr=proc.stderr[:4000])
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}'}


def collect(probe_tools=False):
    linux = sys.platform.startswith('linux')
    result = dict(schema=1, board_validation='待板端验证', host_is_linux=linux,
                  os=dict(system=platform.system(), release=platform.release(),
                          os_release=read('/etc/os-release') if linux else 'not Linux'),
                  python=dict(version=sys.version, executable=sys.executable,
                              bits=struct.calcsize('P') * 8, implementation=platform.python_implementation(),
                              abi=getattr(sys.implementation, 'cache_tag', None)),
                  cpu=dict(machine=platform.machine(), logical_cores=os.cpu_count(),
                           info=read('/proc/cpuinfo') if linux else 'not Linux'),
                  libc=dict(zip(('name', 'version'), platform.libc_ver())),
                  memory=read('/proc/meminfo') if linux else 'not Linux',
                  display=dict(environment={k: os.environ.get(k) for k in ('DISPLAY','WAYLAND_DISPLAY','XDG_SESSION_TYPE')},
                               connectors=[]), video=[], audio={}, npu={}, commands={}, packages={})
    for name in ['mediapipe','torch','onnxruntime','opencv-contrib-python','numpy','aiohttp','sherpa-onnx','sherpa-onnx-core']:
        try: result['packages'][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: result['packages'][name] = 'not installed'
    if linux:
        for node in sorted(glob.glob('/sys/class/video4linux/video*')):
            device = '/dev/' + Path(node).name
            result['video'].append(dict(device=device, name=read(node + '/name'),
                                        read_permission=os.access(device, os.R_OK),
                                        write_permission=os.access(device, os.W_OK), opened=False))
        for node in sorted(glob.glob('/sys/class/drm/card*-*')):
            if Path(node, 'status').exists():
                result['display']['connectors'].append(dict(name=Path(node).name,
                                                            status=read(node + '/status'), modes=read(node + '/modes')))
        result['display']['framebuffers'] = {p: read(p) for p in glob.glob('/sys/class/graphics/fb*/virtual_size')}
        result['audio'] = dict(cards=read('/proc/asound/cards'), pcm=read('/proc/asound/pcm'),
                               nodes=sorted(glob.glob('/dev/snd/*')), opened=False)
        modules = read('/proc/modules')
        result['npu'] = dict(nodes=sorted(glob.glob('/dev/dri/renderD*') + glob.glob('/dev/rknpu*')),
                             module_lines=[line for line in modules.splitlines() if 'rknpu' in line.lower()] if isinstance(modules,str) else modules,
                             opened=False, usable='待板端验证；设备节点或模块存在不证明NPU推理可用')
    if probe_tools and linux:
        for name, argv in [('v4l2',['v4l2-ctl','--list-devices']), ('playback',['aplay','-l']),
                           ('recording',['arecord','-l']), ('display',['xrandr','--query'])]:
            result['commands'][name] = command(argv)
    result['limits'] = ['Inventory only; no camera capture, audio playback or NPU inference',
                        'No sudo, package installation, services, partitions or device-tree changes',
                        'No board identity or display/touch compatibility certification']
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--probe-tools', action='store_true')
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    text = json.dumps(collect(args.probe_tools), ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding='utf-8')
    else:
        print(text)


if __name__ == '__main__': main()
