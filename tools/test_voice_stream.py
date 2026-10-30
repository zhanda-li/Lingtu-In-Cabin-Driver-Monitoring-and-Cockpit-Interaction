"""Check always-listening engine selection without loading neural models."""
import sys
import unittest
import ast
import copy
from types import SimpleNamespace
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


class PlaybackReceipt(unittest.IsolatedAsyncioTestCase):
    async def run_receipt(self, *, played=True, round=3, owner=True):
        # Compile the actual production branch without constructing Hub or devices.
        path = Path(__file__).resolve().parents[1] / 'ui/server.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        branch = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                      and isinstance(n.test, ast.Compare)
                      and any(isinstance(c, ast.Constant) and c.value == 'voice_spoken'
                              for c in n.test.comparators))
        branch = copy.copy(branch)
        branch.orelse = []
        wrapper = ast.parse('async def receipt(hub, req, ws):\n    pass\n')
        wrapper.body[0].body = [branch]
        ast.fix_missing_locations(wrapper)
        messages = []

        async def send(ws, message):
            messages.append(message)

        namespace = {'kind': 'voice_spoken', 'voice_send': send}
        exec(compile(wrapper, str(path), 'exec'), namespace)
        ear = SimpleNamespace(state='speak', round=3, follow_s=10)

        def complete(follow=True):
            ear.state = 'follow' if follow else 'idle'

        ear.answer_done = complete
        ws = object()
        hub = SimpleNamespace(ear=ear, ear_ws=ws if owner else object(),
                              ear_task=None, pending_do=None)
        await namespace['receipt'](hub, {'played': played, 'round': round, 'reason': 'muted'}, ws)
        return ear.state, messages

    async def test_unplayed_does_not_open_followup(self):
        state, messages = await self.run_receipt(played=False)
        self.assertEqual(state, 'idle')
        self.assertEqual(messages[0]['ev'], 'idle')

    async def test_completed_opens_followup(self):
        state, messages = await self.run_receipt()
        self.assertEqual(state, 'follow')
        self.assertEqual(messages[0]['ev'], 'follow')

    async def test_stale_receipt_is_ignored(self):
        self.assertEqual(await self.run_receipt(round=2), ('speak', []))

    async def test_non_owner_receipt_is_ignored(self):
        self.assertEqual(await self.run_receipt(owner=False), ('speak', []))


if __name__ == '__main__':
    unittest.main()
