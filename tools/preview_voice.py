"""Generate real TTS previews without playing audio or starting other services."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ui.tts import ServerVoice


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(ROOT / 'ui/config.json'))
    parser.add_argument('--output', default=str(ROOT / 'runs/voice_previews'))
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding='utf-8'))['tts']
    cfg['enabled'] = False  # No background worker, speaker playback, or integrations.
    voice = ServerVoice(cfg)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    for emotion, text in (
        ('normal', '主人，我是小瑞！今天也一起出发吧。路上有我陪着你，累了就告诉我哦。'),
        ('alert', '主人，你已经很困了。请在安全的地方停车休息，我陪你等一会儿。'),
    ):
        data = voice._edge_mp3(text, emotion)
        if len(data) < 1000:
            raise RuntimeError('Synthesis returned insufficient audio; preview not saved.')
        path = output / ('sprite_' + emotion + '.mp3')
        path.write_bytes(data)
        print(json.dumps({'file': str(path.resolve()), 'bytes': len(data),
                          'voice': voice.edge_voice, 'emotion': emotion}))


if __name__ == '__main__':
    main()
