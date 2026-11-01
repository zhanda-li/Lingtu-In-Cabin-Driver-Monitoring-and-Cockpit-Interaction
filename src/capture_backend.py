"""Camera device/backend selection only; frame timing stays in CameraSource."""
import math
import os
import platform

import cv2


def camera_device(value):
    """Keep Linux device paths as strings and OpenCV numeric indices as ints."""
    text = str(value).strip()
    return int(text) if text.isdecimal() else text


def _positive(value, name):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and > 0")
    return value


def open_camera(cam=0, size=(1280, 720), backend=None, fps=None):
    """Environment overrides are shared by CLI and UI; no resampling here.

    Default platform backend can fall back to CAP_ANY if opening fails.
    Explicit backend choices fail visibly rather than silently changing backend.
    Width/height/fps are requests; a camera may negotiate different values.
    """
    device = camera_device(os.environ.get('DMS_CAMERA_DEVICE', cam))
    width = int(_positive(os.environ.get('DMS_CAMERA_WIDTH', size[0]), 'camera width'))
    height = int(_positive(os.environ.get('DMS_CAMERA_HEIGHT', size[1]), 'camera height'))
    if width < 1 or height < 1:
        raise ValueError('camera dimensions must be >= 1')
    fps = os.environ.get('DMS_CAMERA_FPS', fps)
    fps = None if fps is None else _positive(fps, 'camera fps')
    choice = os.environ.get('DMS_CAMERA_BACKEND', backend or 'platform').lower()
    choices = {'auto': cv2.CAP_ANY, 'dshow': cv2.CAP_DSHOW, 'v4l2': cv2.CAP_V4L2}
    if choice == 'platform':
        selected = {'Windows': 'dshow', 'Linux': 'v4l2'}.get(platform.system(), 'auto')
    elif choice in choices:
        selected = choice
    else:
        raise ValueError(f'Unknown camera backend: {choice}; use platform/auto/dshow/v4l2')
    attempts = [selected]
    if choice == 'platform' and selected != 'auto':
        attempts.append('auto')
    for name in attempts:
        cap = cv2.VideoCapture(device, choices[name])
        try:
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                if fps is not None:
                    cap.set(cv2.CAP_PROP_FPS, fps)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                return cap
        except Exception:
            cap.release()
            raise
        cap.release()
    raise RuntimeError(f'打不开摄像头 {device} (backends: {", ".join(attempts)})')
