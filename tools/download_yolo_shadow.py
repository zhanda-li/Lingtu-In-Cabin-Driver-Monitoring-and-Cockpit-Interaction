"""Download only the verified public checkpoints into the isolated shadow folder."""
import hashlib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = {
    'best.pt':'739f7de6e8262b91f393f5591a7099e410b7c5eb6929f53632c53d2bdd8fea68',
    'best_yawn.pt':'3041073b081fa6a5490d75d7beba278a500eb8ac67cdfcb2cb35ef6668ef0905',
}

def main():
    folder = ROOT/'models/yolo_shadow'
    folder.mkdir(exist_ok=True)
    for name,digest in WEIGHTS.items():
        path = folder/name
        if path.exists():
            data = path.read_bytes()
        else:
            url = 'https://raw.githubusercontent.com/hongshenlv/Fatigue-Detection/master/Blink_detection/'+name
            with urllib.request.urlopen(url,timeout=30) as stream:
                data = stream.read(10_000_001)
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f'{name}: checkpoint hash mismatch; refusing to overwrite')
        if not path.exists():
            path.write_bytes(data)
        print(name,'SHA256 verified')

if __name__ == '__main__':
    main()
