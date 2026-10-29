"""Run in a separate Linux RKNN-Toolkit2 environment; FP conversion by default."""
import argparse
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('onnx', type=Path)
    ap.add_argument('--calibration', type=Path, help='Explicit INT8 dataset list (public held-out ROI calibration set)')
    args = ap.parse_args()
    if not args.onnx.is_file():
        ap.error('ONNX model does not exist')
    if args.calibration and not args.calibration.is_file():
        ap.error('Calibration list does not exist')
    from rknn.api import RKNN
    model = RKNN(verbose=True)
    try:
        model.config(target_platform='rk3568', mean_values=[[0,0,0]], std_values=[[255,255,255]])
        if model.load_onnx(model=str(args.onnx)) != 0:
            raise RuntimeError('RKNN load_onnx failed')
        if model.build(do_quantization=bool(args.calibration),
                       dataset=str(args.calibration) if args.calibration else None) != 0:
            raise RuntimeError('RKNN build failed')
        target = args.onnx.with_suffix('.int8.rknn' if args.calibration else '.fp.rknn')
        if model.export_rknn(str(target)) != 0:
            raise RuntimeError('RKNN export failed')
        print(target)
    finally:
        model.release()

if __name__ == '__main__':
    main()
