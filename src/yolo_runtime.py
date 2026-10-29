"""Torch-free CPU inference for the verified two-class ONNX exports."""
import ast
import numpy as np
from PIL import Image


def preprocess(roi, size=224):
    image = Image.fromarray(np.ascontiguousarray(roi[:, :, ::-1]))
    w, h = image.size
    dims = (size, int(size*h/w)) if w <= h else (int(size*w/h), size)
    image = image.resize(dims, Image.Resampling.BILINEAR)
    x, y = round((dims[0]-size)/2), round((dims[1]-size)/2)
    image = image.crop((x,y,x+size,y+size))
    return np.ascontiguousarray(np.asarray(image, np.float32).transpose(2,0,1)[None]/255.)


class OnnxClassifier:
    backend = 'onnx_cpu'
    def __init__(self, path, positive, negative):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), sess_options=opts, providers=['CPUExecutionProvider'])
        metadata = self.session.get_modelmeta().custom_metadata_map
        if metadata.get('task') != 'classify':
            raise ValueError('Expected classification ONNX metadata')
        self.names = ast.literal_eval(metadata['names'])
        norm = lambda s: s.lower().replace(' ', '_').replace('-', '_')
        pos = [i for i,n in self.names.items() if norm(n) in positive]
        neg = [i for i,n in self.names.items() if norm(n) in negative]
        if len(self.names) != 2 or len(pos) != 1 or len(neg) != 1 or pos == neg:
            raise ValueError(f'Unexpected names {self.names}')
        if self.session.get_inputs()[0].shape != [1,3,224,224]:
            raise ValueError('Only verified fixed-size 224 export supported')
        self.index = pos[0]

    def __call__(self, roi):
        x = preprocess(roi)
        values = self.session.run(None, {self.session.get_inputs()[0].name:x})[0]
        if values.shape != (1,2) or not np.isfinite(values).all():
            raise ValueError('Invalid classification output')
        if (values < 0).any() or (values > 1).any() or abs(float(values.sum())-1) > .001:
            raise ValueError('Expected probabilities, refusing to guess softmax semantics')
        return float(values[0,self.index])


class RknnClassifier(OnnxClassifier):
    """Opt-in Lite2 backend. Load/inference errors permanently fall back to ONNX CPU."""
    def __init__(self, path, positive, negative):
        super().__init__(path, positive, negative)
        self.npu = None
        self.fallback_reason = None
        from pathlib import Path
        try:
            from rknnlite.api import RKNNLite
            self.npu = RKNNLite()
            if self.npu.load_rknn(str(Path(path).with_suffix('.fp.rknn'))) != 0:
                raise RuntimeError('RKNN load failed')
            if self.npu.init_runtime() != 0:
                raise RuntimeError('RKNN runtime initialization failed')
            self.backend = 'rknn_lite2'
        except Exception as exc:
            self._fallback(exc)

    def _fallback(self, exc):
        self.fallback_reason = f'{type(exc).__name__}: {exc}'
        if self.npu is not None:
            self.npu.release()
        self.npu = None
        self.backend = 'onnx_cpu_fallback'

    def __call__(self, roi):
        if self.npu is not None:
            try:
                tensor = np.rint(preprocess(roi).transpose(0,2,3,1)*255).astype(np.uint8)
                result = self.npu.inference(inputs=[tensor],data_format=['nhwc'])
                values = np.asarray(result[0]).reshape(-1)
                if values.size != 2 or not np.isfinite(values).all() or (values<0).any() or (values>1).any() or abs(float(values.sum())-1) > .001:
                    raise ValueError('Unexpected NPU probability output')
                return float(values[self.index])
            except Exception as exc:
                self._fallback(exc)
        return super().__call__(roi)

    def close(self):
        if self.npu is not None:
            self.npu.release()
            self.npu = None
