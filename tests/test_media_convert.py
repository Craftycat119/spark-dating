import shutil
import subprocess

import pytest

from app import storage
from app.config import settings

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="нет ffmpeg")


def _webm(rel: str, audio_only: bool = False) -> None:
    path = settings.media_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    src = ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"]
    if not audio_only:
        src = ["-f", "lavfi", "-i", "testsrc=size=160x160:rate=10:duration=1", *src]
    codec = ["-c:a", "libopus"] if audio_only else ["-c:v", "libvpx", "-c:a", "libopus"]
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *src, *codec, str(path)], check=True)


def test_circle_webm_becomes_mp4():
    _webm("chat/999/c.webm")
    rel = storage.to_playable("chat/999/c.webm", "circle")
    assert rel == "chat/999/c.mp4"
    assert (settings.media_dir / rel).read_bytes()[4:8] == b"ftyp"
    assert not (settings.media_dir / "chat/999/c.webm").exists()


def test_voice_webm_becomes_m4a():
    _webm("chat/999/v.webm", audio_only=True)
    assert storage.to_playable("chat/999/v.webm", "voice") == "chat/999/v.m4a"


def test_broken_file_kept_as_is():
    path = settings.media_dir / "chat/999/bad.webm"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a video")
    assert storage.to_playable("chat/999/bad.webm", "circle") == "chat/999/bad.webm"
    assert path.exists()


def test_mp4_untouched():
    assert storage.to_playable("chat/999/x.mp4", "video") == "chat/999/x.mp4"
