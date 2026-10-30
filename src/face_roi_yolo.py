"""Optional shadow classifier. Never imports or modifies risk fusion.

P contains pixel coordinates from the existing FaceExtractor. Left/right refer
to the driver's anatomical sides (unmirrored camera), not screen positions.
"""
import math
import time
import numpy as np
import queue
import threading

REGIONS = {'left': (362, 263, 386, 374, 385, 373),
           'right': (33, 133, 145, 159, 144, 160),
           'mouth': (61, 291, 13, 14, 12, 15)}


def crop_roi(frame, points, ids):
    if frame is None or points is None or frame.ndim != 3:
        return None
    try:
        xy = np.asarray([points[i] for i in ids], float)
    except (KeyError, IndexError, TypeError):
        return None
    if xy.shape != (len(ids), 2) or not np.isfinite(xy).all():
        return None
    lo, hi = xy.min(0), xy.max(0)
    width = hi[0] - lo[0]
    if width < 4:
        return None
    # Width-based padding still covers closed eyelids, unlike height scaling.
    pad = np.array([width * .3, width * .25])
    h, w = frame.shape[:2]
    if (lo < 0).any() or hi[0] >= w or hi[1] >= h:
        return None
    a = np.maximum(np.floor(lo - pad), 0).astype(int)
    b = np.minimum(np.ceil(hi + pad), [w, h]).astype(int)
    if min(b - a) < 4:
        return None
    return frame[a[1]:b[1], a[0]:b[0]].copy()


class Classifier:
    def __init__(self, path, positive, negative, imgsz=224):
        from ultralytics import YOLO
        self.model = YOLO(str(path))
        if self.model.task != 'classify':
            raise ValueError(f'{path}: expected classify, got {self.model.task}')
        names = self.model.names
        norm = lambda s: s.lower().replace(' ', '_').replace('-', '_')
        pos = [i for i, n in names.items() if norm(n) in positive]
        neg = [i for i, n in names.items() if norm(n) in negative]
        if len(names) != 2 or len(pos) != 1 or len(neg) != 1 or pos == neg:
            raise ValueError(f'Unrecognized class mapping: {names}')
        self.index, self.imgsz = pos[0], imgsz

    def __call__(self, roi):
        result = self.model.predict(roi, imgsz=self.imgsz, device='cpu', verbose=False)[0]
        p = float(result.probs.data[self.index].cpu())
        if not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError('Invalid model probability')
        return p


class Temporal:
    def __init__(self):
        self.last = None
        self.smooth = {}
        self.start = {}
        self.fired = set()

    def update(self, now, left, right, mouth, mar):
        if not math.isfinite(now):
            raise ValueError('Timestamp must be finite')
        if self.last is not None and (now <= self.last or now - self.last > .5):
            self.smooth.clear(); self.start.clear(); self.fired.clear()
        dt = max(0, now - self.last) if self.last is not None else 0
        self.last = now
        values = {}
        for k, p in [('left', left), ('right', right), ('mouth', mouth)]:
            if p is None or not math.isfinite(p) or not 0 <= p <= 1:
                self.smooth.pop(k, None)
                values[k] = None
            else:
                alpha = 1 - math.exp(-dt / .12)
                self.smooth[k] = self.smooth.get(k, p) * (1-alpha) + p*alpha
                values[k] = self.smooth[k]
        out = dict(eye_left_open_prob=values['left'], eye_right_open_prob=values['right'],
                   yawn_probability=values['mouth'])
        for side in ['left', 'right']:
            p = values[side]
            out[f'eye_{side}_status'] = ('invalid' if p is None else
                                        'open' if p > .7 else 'closed' if p < .3 else 'uncertain')
            out[f'eye_{side}_confidence'] = None if p is None else max(p, 1-p)
        p = values['mouth']
        out['mouth_confidence'] = None if p is None else max(p, 1-p)
        eye_valid = values['left'] is not None and values['right'] is not None
        mouth_valid = values['mouth'] is not None and mar is not None and math.isfinite(mar)
        for key, valid, active, threshold in [
            ('eye', eye_valid, eye_valid and max(values['left'], values['right']) < .3, .8),
            ('yawn', mouth_valid, mouth_valid and values['mouth'] > .8 and mar > .55, 1.5)]:
            event = 'none' if valid else 'invalid'
            if not valid:
                self.start.pop(key, None); self.fired.discard(key)
            elif active:
                self.start.setdefault(key, now)
            else:
                began = self.start.pop(key, None)
                if key == 'eye' and began is not None and min(values['left'],values['right']) > .7 and .05 <= now-began < .8:
                    event = 'blink'
                self.fired.discard(key)
            duration = now - self.start[key] if key in self.start else 0.
            if duration >= threshold and key not in self.fired:
                event = 'long_closure' if key == 'eye' else 'yawn_candidate'
                self.fired.add(key)
            out[key + ('_closed_duration' if key == 'eye' else '_duration')] = duration
            out[key + '_event'] = event
            out[key + '_status'] = 'invalid' if not valid else ('active' if active else 'inactive')
        return out


class FaceRoiYolo:
    def __init__(self, eye_path, mouth_path):
        import os
        from pathlib import Path
        factory = Classifier
        if os.environ.get('DMS_YOLO_BACKEND', 'pt') in ('onnx', 'rknn'):
            from yolo_runtime import OnnxClassifier, RknnClassifier
            factory = RknnClassifier if os.environ['DMS_YOLO_BACKEND'] == 'rknn' else OnnxClassifier
            eye_path, mouth_path = Path(eye_path).with_suffix('.onnx'), Path(mouth_path).with_suffix('.onnx')
        elif os.environ.get('DMS_YOLO_BACKEND', 'pt') != 'pt':
            raise ValueError('Supported backends: pt, onnx, rknn')
        self.eye = factory(eye_path, {'open', 'open_eye', 'opened'}, {'closed', 'close', 'closed_eye'})
        self.mouth = factory(mouth_path, {'yawn', 'yawning'}, {'no_yawn', 'not_yawn', 'no_yawning'})
        self.temporal = Temporal()

    def process(self, frame, points, mar, now):
        start = time.perf_counter()
        probs, errors = {}, []
        for key, ids in REGIONS.items():
            roi = crop_roi(frame, points, ids)
            probs[key] = None
            if roi is not None:
                try:
                    probs[key] = (self.mouth if key == 'mouth' else self.eye)(roi)
                except Exception as exc:
                    errors.append(f'{key}: {type(exc).__name__}: {exc}')
        out = self.temporal.update(now, probs['left'], probs['right'], probs['mouth'], mar)
        out.update(mode='shadow', inference_ms=(time.perf_counter()-start)*1000, errors=errors,
                   eye_backend=getattr(self.eye,'backend','pt_cpu'),
                   mouth_backend=getattr(self.mouth,'backend','pt_cpu'),
                   fallback_reasons=[v for v in [getattr(self.eye,'fallback_reason',None),getattr(self.mouth,'fallback_reason',None)] if v],
                   probability_kind='uncalibrated_class_probability')
        return out

    def close(self):
        for adapter in [self.eye,self.mouth]:
            if hasattr(adapter,'close'):
                adapter.close()


class AsyncFaceRoiYolo:
    """One worker, one pending frame; replaces queued stale work instead of blocking DMS."""
    def __init__(self, eye_path, mouth_path):
        self.detector = FaceRoiYolo(eye_path, mouth_path)
        self.pending = queue.Queue(maxsize=1)
        self.latest = None
        self.generation = 0
        self._state_lock = threading.Lock()
        self.stopped = threading.Event()
        self.worker = threading.Thread(target=self._run, name='dms-yolo-shadow', daemon=True)
        self.worker.start()

    def _run(self):
        while not self.stopped.is_set():
            try:
                frame, points, mar, timestamp, generation = self.pending.get(timeout=.1)
            except queue.Empty:
                continue
            try:
                if getattr(self, '_worker_generation', None) != generation:
                    self.detector.temporal = Temporal()
                    self._worker_generation = generation
                out = self.detector.process(frame, points, mar, timestamp)
                out['sample_timestamp'] = timestamp
                with self._state_lock:
                    if generation == self.generation and not self.stopped.is_set():
                        self.latest = out
            except Exception as exc:
                with self._state_lock:
                    if generation == self.generation and not self.stopped.is_set():
                        self.latest = dict(Temporal().update(timestamp,None,None,None,None),
                                           mode='shadow',sample_timestamp=timestamp,
                                           errors=[f'{type(exc).__name__}: {exc}'])
        self.detector.close()

    def process(self, frame, points, mar, now):
        # Face loss invalidates published evidence immediately, even when inference is busy.
        invalid_roi = points is None or any(crop_roi(frame,points,ids) is None for ids in REGIONS.values())
        with self._state_lock:
            discontinuity = hasattr(self, '_last_submitted') and (now <= self._last_submitted or now-self._last_submitted > .5)
            if invalid_roi or discontinuity:
                self.generation += 1
                self.latest = None
            self._last_submitted = now
            generation = self.generation
            result = self.latest
        item = (frame.copy() if frame is not None else None,
                None if points is None else {k:v.copy() for k,v in points.items()}, mar, now, generation)
        try:
            self.pending.get_nowait()
        except queue.Empty:
            pass
        try:
            self.pending.put_nowait(item)
        except queue.Full:
            pass
        if result is None or now - result['sample_timestamp'] > .5 or now < result['sample_timestamp']:
            return dict(Temporal().update(now,None,None,None,None), mode='shadow',
                        errors=[], pending=True)
        return dict(result, pending=False, result_age_seconds=now-result['sample_timestamp'])

    def close(self):
        self.stopped.set()
