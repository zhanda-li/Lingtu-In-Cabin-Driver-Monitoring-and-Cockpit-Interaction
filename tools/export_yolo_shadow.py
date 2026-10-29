"""Desktop-only ONNX export and parity on identical model-preprocessed tensors."""
import json
from pathlib import Path
import numpy as np
import torch
import onnxruntime as ort
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]

def main():
    report = []
    for name in ['best', 'best_yawn']:
        model = YOLO(str(ROOT / 'models/yolo_shadow' / (name+'.pt')))
        exported = model.export(format='onnx', imgsz=224, batch=1, dynamic=False,
                                opset=12, simplify=False)
        session = ort.InferenceSession(str(exported), providers=['CPUExecutionProvider'])
        # Reuse actual classify pipeline, including RGB/center crop/normalization.
        images = [np.full((90,140,3), 127, np.uint8)]
        import cv2
        samples = sorted((ROOT/'datasets/mrlEyes_2018_01').rglob('*.png'))
        images += [cv2.imread(str(p)) for p in samples[::max(1,len(samples)//5)][:5]]
        model.predict(images[0], imgsz=224, device='cpu', verbose=False)
        differences = []
        for image in images:
            x = model.predictor.preprocess([image]).cpu()
            with torch.inference_mode():
                raw = model.model(x)
            pt = (raw[0] if isinstance(raw, tuple) else raw).cpu().numpy()
            onnx = session.run(None, {session.get_inputs()[0].name: x.numpy()})[0]
            np.testing.assert_allclose(onnx, pt, rtol=1e-4, atol=1e-5)
            differences.append(float(np.max(np.abs(onnx-pt))))
        report.append(dict(model=name, names=model.names, onnx=str(exported),
            input_shape=session.get_inputs()[0].shape, output_shape=session.get_outputs()[0].shape,
            samples=len(differences), max_abs_error=max(differences),
            note='Identical tensors; export parity only, not recognition accuracy'))
    (ROOT/'docs/yolo_onnx_parity.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
