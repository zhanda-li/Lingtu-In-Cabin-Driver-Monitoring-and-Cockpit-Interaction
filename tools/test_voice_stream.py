"""Check always-listening engine selection without loading neural models."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ui'))
from voice import asr_stream


class EngineSelection(unittest.TestCase):
    def choose(self, cfg, stream_ok=True):
        calls = []

        class Stream:
            ready = stream_ok
            why = 'unavailable' if not stream_ok else ''

            def __init__(self, cfg):
                calls.append('stream')

        class Whisper:
            ready = True

            def __init__(self, cfg, local=None):
                calls.append('whisper')

        with patch.object(asr_stream, 'StreamAsr', Stream), patch.object(asr_stream, 'WhisperAsr', Whisper):
            asr_stream.make_asr({'asr': cfg})
        return calls

    def test_browser_preference_does_not_disable_streaming(self):
        self.assertEqual(self.choose({'prefer': 'browser'}), ['stream'])

    def test_stream_failure_keeps_whisper_fallback(self):
        self.assertEqual(self.choose({'prefer': 'browser'}, False), ['stream', 'whisper'])

    def test_explicit_local_preference_is_retained(self):
        self.assertEqual(self.choose({'prefer': 'local'}), ['whisper'])

    def test_separate_wake_preference(self):
        self.assertEqual(self.choose({'prefer': 'browser', 'wake_prefer': 'whisper'}), ['whisper'])


if __name__ == '__main__':
    unittest.main()
