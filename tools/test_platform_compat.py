"""PC contract tests: simulated platform dispatch, never Linux hardware claims."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from src import capture_backend as capture
from src import audio_playback as audio
from ui.tts import ServerVoice


class CameraCompatibility(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {k: v for k, v in os.environ.items()
                                         if not k.startswith('DMS_CAMERA_')}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_platform_defaults_and_frame_contract(self):
        from live import CameraSource
        import numpy as np
        frame = np.zeros((24, 32, 3), dtype=np.uint8)
        for system, backend in [('Windows', capture.cv2.CAP_DSHOW),
                                ('Linux', capture.cv2.CAP_V4L2), ('Darwin', capture.cv2.CAP_ANY)]:
            cap = Mock()
            cap.read.return_value = (True, frame)
            with patch.object(capture.platform, 'system', return_value=system), \
                    patch.object(capture.cv2, 'VideoCapture', return_value=cap) as open_:
                src = CameraSource()
                open_.assert_called_once_with(0, backend)
                self.assertEqual(src.media_time(), 0.)
                actual, ok = src.read()
                self.assertTrue(ok)
                self.assertIs(actual, frame)
                self.assertEqual(src.frames, 1)
                src.release()
                cap.release.assert_called_once()

    def test_path_resolution_fps_and_auto_fallback(self):
        bad, good = Mock(), Mock()
        bad.isOpened.return_value = False
        with patch.dict(os.environ, {'DMS_CAMERA_DEVICE': '/dev/video2', 'DMS_CAMERA_WIDTH': '640',
                                    'DMS_CAMERA_HEIGHT': '480', 'DMS_CAMERA_FPS': '30'}), \
                patch.object(capture.platform, 'system', return_value='Linux'), \
                patch.object(capture.cv2, 'VideoCapture', side_effect=[bad, good]) as open_:
            self.assertIs(capture.open_camera(), good)
            self.assertEqual(open_.call_args_list[0].args, ('/dev/video2', capture.cv2.CAP_V4L2))
            self.assertEqual(open_.call_args_list[1].args, ('/dev/video2', capture.cv2.CAP_ANY))
            bad.release.assert_called_once()
            for prop, value in [(capture.cv2.CAP_PROP_FRAME_WIDTH, 640),
                                (capture.cv2.CAP_PROP_FRAME_HEIGHT, 480),
                                (capture.cv2.CAP_PROP_FPS, 30)]:
                good.set.assert_any_call(prop, value)

    def test_explicit_auto_and_backend_failure(self):
        for backend in ['auto', 'v4l2']:
            cap = Mock(); cap.isOpened.return_value = False
            with patch.object(capture.cv2, 'VideoCapture', return_value=cap) as open_:
                with self.assertRaises(RuntimeError):
                    capture.open_camera(backend=backend)
                self.assertEqual(open_.call_count, 1)
                cap.release.assert_called_once()

    def test_invalid_configuration_does_not_open_device(self):
        for settings in [dict(backend='bad'), dict(fps=0), dict(fps=float('nan')), dict(size=(-1, 720))]:
            with patch.object(capture.cv2, 'VideoCapture') as open_:
                with self.assertRaises(ValueError):
                    capture.open_camera(**settings)
                open_.assert_not_called()
        self.assertEqual(capture.camera_device('2'), 2)
        self.assertEqual(capture.camera_device('/dev/v4l/by-id/camera'), '/dev/v4l/by-id/camera')


class AudioCompatibility(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {k: v for k, v in os.environ.items()
                                         if k not in ('DMS_AUDIO_PLAYER', 'DMS_TTS_COMMAND', 'DMS_AUDIO_DEVICE')},
                              clear=True); self.env.start()
        self.addCleanup(self.env.stop)

    def voice(self, **cfg):
        return ServerVoice({'enabled': False, 'server': cfg})

    def test_missing_player_and_missing_device_are_explicit(self):
        ok, detail = audio.play_file('clip.mp3')
        self.assertFalse(ok); self.assertIn('not configured', detail)
        ok, detail = audio.play_file('clip.mp3', ['player', '-D', '{device}', '{file}'])
        self.assertFalse(ok); self.assertIn('DMS_AUDIO_DEVICE', detail)
        ok, detail = audio.play_file('clip.mp3', ['nonexistent-dms-player-1234', '{file}'])
        self.assertFalse(ok); self.assertIn('not found', detail)

    def test_no_shell_and_literal_arguments(self):
        command = [sys.executable, '-c', 'import sys; print(sys.argv[1])', '{file}']
        value = "a b'$(untrusted);.mp3"
        ok, detail = audio.play_file(value, json.dumps(command))
        self.assertTrue(ok, detail); self.assertEqual(detail, value)

    def test_player_device_error_and_timeout(self):
        command = [sys.executable, '-c', "import sys; print('no audio device'); sys.exit(7)", '{file}']
        ok, detail = audio.play_file('a.mp3', command)
        self.assertFalse(ok); self.assertIn('exit 7', detail); self.assertIn('no audio device', detail)
        ok, detail = audio.play_file('a.mp3', [sys.executable, '-c', 'import time; time.sleep(5)', '{file}'], timeout=.1)
        self.assertFalse(ok); self.assertIn('timed out', detail)

    def test_cancelled_audio_does_not_spawn(self):
        event = threading.Event(); event.set()
        with patch.object(audio.subprocess, 'Popen') as popen:
            ok, _ = audio.play_file('a.mp3', [sys.executable, '{file}'], stop_event=event)
            self.assertFalse(ok); popen.assert_not_called()

    def test_windows_mp3_and_sapi_paths_are_retained(self):
        voice = self.voice()
        proc = Mock(); proc.communicate.return_value = ('XQOK', None); proc.returncode = 0
        with patch('ui.tts.sys.platform', 'win32'), patch('ui.tts.subprocess.Popen', return_value=proc) as popen:
            self.assertTrue(voice._play_mp3("D:/test clip.mp3")[0])
            self.assertEqual(popen.call_args.args[0][0], 'powershell')
            self.assertIn('System.Windows.Media.MediaPlayer', popen.call_args.args[0][-1])
            voice._sapi_once('测试', 'normal')
            self.assertIn('System.Speech', popen.call_args.args[0][-1])
            self.assertEqual(voice.spoken, 1)

    def test_linux_ui_and_live_tts_do_not_call_powershell(self):
        from live import TTSWorker
        voice = self.voice()
        with patch('ui.tts.sys.platform', 'linux'), patch('ui.tts.subprocess.Popen') as popen:
            voice._sapi_once('测试', 'normal')
            self.assertIn('not configured', voice.last_error)
            self.assertFalse(voice._play_mp3('/tmp/clip.mp3')[0])
            popen.assert_not_called()
            worker = TTSWorker(enabled=False); worker.enabled = True
            class EndLoop(Exception):
                pass
            worker.q.get = Mock(side_effect=['测试', EndLoop()])
            with self.assertRaises(EndLoop):
                worker._run()
            self.assertIn('not configured', worker.last_error)

    def test_linux_ui_success_updates_existing_status(self):
        voice = self.voice(tts_command=[sys.executable, '-c', 'import sys; print(sys.argv[1])', '{text}'])
        with patch('ui.tts.sys.platform', 'linux'):
            voice._sapi_once('你好小瑞', 'normal')
        self.assertEqual(voice.spoken, 1)
        self.assertEqual(voice.status()['last_text'], '你好小瑞')
        self.assertIsNone(voice.last_error)

    def test_windows_live_tts_reports_process_failure_without_stopping_queue(self):
        from live import TTSWorker
        worker = TTSWorker(enabled=False); worker.enabled = True
        class EndLoop(Exception):
            pass
        worker.q.get = Mock(side_effect=['测试失败', '测试成功', EndLoop()])
        with patch('live.sys.platform', 'win32'), patch('live.subprocess.run') as run:
            run.side_effect = [subprocess.CalledProcessError(1, 'powershell'), Mock()]
            with self.assertRaises(EndLoop):
                worker._run()
        self.assertEqual(worker.spoken, 1)
        self.assertIn('CalledProcessError', worker.last_error)
        self.assertTrue(run.call_args.kwargs['check'])


if __name__ == '__main__':
    unittest.main()
