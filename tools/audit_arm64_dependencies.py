"""Record local dependency declarations, never install or resolve target wheels.

Windows metadata can contain Linux markers; it does not substitute for ARM64
wheel METADATA or a real target resolver. No network or board access.
"""
import importlib.metadata as metadata
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
NAMES = ['mediapipe', 'torch', 'onnxruntime', 'opencv-contrib-python', 'numpy',
         'aiohttp', 'sherpa-onnx', 'sherpa-onnx-core', 'scipy', 'sounddevice',
         'matplotlib', 'Pillow', 'edge-tts', 'certifi', 'pyserial']


def main():
    packages = {}
    for name in NAMES:
        try:
            dist = metadata.distribution(name)
            packages[name] = dict(version=dist.version,
                                  requires_python=dist.metadata.get('Requires-Python'),
                                  requires_dist=dist.requires or [])
        except metadata.PackageNotFoundError:
            packages[name] = dict(error='not installed on this PC')
    report = dict(host=platform.platform(), python=sys.version, packages=packages,
                  target_install_tested=False,
                  unresolved=['ARM64 wheel availability and full transitive graph',
                              'CPU torch wheel metadata (not default PyPI CUDA dependencies)',
                              'sherpa-onnx-core matching ARM64 wheel',
                              'PortAudio, ALSA/Pulse/PipeWire device availability',
                              'OpenCV shared libraries, V4L2, CPU instruction compatibility',
                              'Optional Whisper/numba/llvmlite not included in runtime draft'])
    path = ROOT / 'docs/validation/arm64_dependency_audit.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(path)


if __name__ == '__main__':
    main()
