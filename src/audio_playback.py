"""Explicit argv-based audio adapter. No shell, package install or device guess."""
import json
import os
import shutil
import subprocess


class AudioError(RuntimeError):
    pass


def command_argv(command, placeholder, value, device=None):
    """Commands must be JSON argv arrays (or config lists), never shell strings."""
    if not command:
        raise AudioError('Linux audio is not configured: set DMS_AUDIO_PLAYER '
                         '(file playback) or DMS_TTS_COMMAND (text synthesis/playback)')
    try:
        parts = json.loads(command) if isinstance(command, str) else command
    except (ValueError, TypeError) as exc:
        raise AudioError('Audio command must be a JSON argv array') from exc
    token = '{' + placeholder + '}'
    if (not isinstance(parts, list) or not parts or
            not all(isinstance(p, str) and p for p in parts) or
            not any(token in p for p in parts[1:])):
        raise AudioError(f'Audio command must be a nonempty argv array containing {token} in its arguments')
    if any('{device}' in p for p in parts) and not device:
        raise AudioError('Audio command requires DMS_AUDIO_DEVICE / audio_device')
    # Substitute argument values, not shell syntax. Apostrophes/spaces are literal.
    argv = [p.replace(token, str(value)).replace('{device}', str(device or '')) for p in parts]
    if not shutil.which(argv[0]):
        raise AudioError(f'Audio executable not found: {argv[0]}')
    return argv


def run_audio(command, placeholder, value, timeout=30, device=None,
              on_process=None, stop_event=None):
    """Return (success, detail); unavailable devices/commands cannot crash DMS.

    The configured player owns device selection. A zero exit code is the player's
    success report, not proof that a physical speaker produced sound.
    """
    proc = None
    try:
        argv = command_argv(command, placeholder, value, device)
        if stop_event is not None and stop_event.is_set():
            return False, 'Audio playback cancelled'
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding='utf-8', errors='replace')
        if on_process:
            on_process(proc)
        if stop_event is not None and stop_event.is_set():
            proc.kill()
            proc.communicate()
            return False, 'Audio playback cancelled'
        try:
            output, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return False, f'Audio playback timed out after {timeout}s'
        if proc.returncode:
            return False, f'Audio player/device failed (exit {proc.returncode}): {(output or "").strip()[-2000:]}'
        return True, (output or '').strip()[-2000:]
    except Exception as exc:
        return False, f'{type(exc).__name__}: {exc}'
    finally:
        if on_process:
            on_process(None)


def play_file(path, command=None, **kwargs):
    return run_audio(os.environ.get('DMS_AUDIO_PLAYER', command), 'file', path, **kwargs)


def speak_text(text, command=None, **kwargs):
    return run_audio(os.environ.get('DMS_TTS_COMMAND', command), 'text', text, **kwargs)
