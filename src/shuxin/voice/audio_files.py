from __future__ import annotations

import hashlib
import shutil
import subprocess
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path

from shuxin.voice.users import validate_user_id

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
CHANNELS = 1


@dataclass(frozen=True)
class VoiceTurnPaths:
    session_id: str
    turn_id: str
    session_dir: Path
    input_wav: Path
    reply_mp3: Path


class AudioFileStore:
    """只负责用户音频附件的路径、写入、压缩和哈希。"""

    def __init__(self, shuxin_home: Path, outputs_root: Path, user_id: str) -> None:
        self.user_id = validate_user_id(user_id)
        self.user_root = shuxin_home / "users" / self.user_id
        self.outputs_root = outputs_root / "users" / self.user_id
        self.memory_dir = self.user_root / "memory"
        self.companion_dir = self.user_root / "companion"
        self._ensure_layout()

    def user_shuxin_home(self) -> Path:
        return self.user_root

    def new_turn_paths(self, device_id: str, session_id: str | None = None) -> VoiceTurnPaths:
        safe_device = validate_path_part(device_id)
        selected_session = validate_path_part(session_id or uuid.uuid4().hex)
        turn_id = uuid.uuid4().hex
        session_dir = self.outputs_root / safe_device / selected_session
        session_dir.mkdir(parents=True, exist_ok=True)
        return VoiceTurnPaths(
            session_id=selected_session,
            turn_id=turn_id,
            session_dir=session_dir,
            input_wav=session_dir / f"input-{turn_id}.wav",
            reply_mp3=session_dir / f"reply-{turn_id}.mp3",
        )

    def write_input_wav(self, pcm: bytes, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(CHANNELS)
            wav.setsampwidth(SAMPLE_WIDTH)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(pcm)

    def _ensure_layout(self) -> None:
        for directory in [
            self.user_root,
            self.outputs_root,
            self.memory_dir,
            self.companion_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)


def validate_path_part(value: str) -> str:
    return validate_user_id(value or "default")


def compress_wav_to_mp3(input_path: Path, output_path: Path) -> None:
    """调用 ffmpeg 把输入 wav 压缩成低码率 mono mp3。"""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required for audio compression")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(input_path),
            "-ac",
            "1",
            "-b:a",
            "32k",
            str(output_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def purge_attachment_file(path: Path, *, stop_at: Path | None = None) -> int:
    """Delete an attachment file and best-effort empty parent dirs. Returns bytes freed."""
    size = path.stat().st_size if path.exists() else 0
    path.unlink(missing_ok=True)
    if stop_at is None:
        return size
    current = path.parent
    while current != stop_at and stop_at in current.parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
    return size
