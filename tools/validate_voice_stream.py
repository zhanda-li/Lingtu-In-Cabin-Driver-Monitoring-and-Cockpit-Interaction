"""Replay existing WAV fixtures through real streaming ASR; no accuracy claim."""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ui'))
from asr import wav_bytes_to_float32
from voice.asr_stream import make_asr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(ROOT / 'ui/config.json'))
    parser.add_argument('--samples', default=str(ROOT / 'runs/wake_samples'))
    parser.add_argument('--report', default=str(ROOT / 'runs/voice_stream_validation.json'))
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding='utf-8'))
    asr, note = make_asr(cfg)
    if not asr.ready or not asr.status().get('partial'):
        raise RuntimeError('Streaming ASR unavailable: ' + note)
    rows = []
    for name in ('pos_music', 'pos_goto_media', 'pos_goto_nav', 'pos_rest_stop', 'pos_affirm'):
        samples = wav_bytes_to_float32((Path(args.samples) / (name + '.wav')).read_bytes(), want_sr=16000)
        start = time.perf_counter()
        first = None
        last = ''
        updates = 0
        for offset in range(0, len(samples), 1600):
            text = asr.feed(samples[offset:offset + 1600])
            if text and text != last:
                if first is None:
                    first = round(offset / 16000, 2)
                updates += 1
                last = text
        for _ in range(120):
            asr.feed(np.zeros(1600, dtype=np.float32))
            if asr.endpoint():
                break
        text = asr.finalize()
        row = dict(sample=name, text=text, partial_updates=updates,
                   first_partial_audio_s=first,
                   processing_ms=round((time.perf_counter() - start) * 1000, 1))
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
