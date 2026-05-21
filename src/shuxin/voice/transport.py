from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class DeviceSession:
    """Runtime state for one voice device/session.

    This intentionally mirrors the shape needed by future hardware transports
    without importing the mature Xiaozhi connection stack into ShuXin.
    """

    device_id: str
    client_id: str = ""
    turn_index: int = 0
    metadata: dict[str, str] = field(default_factory=dict)

    def next_reply_path(self, out_dir: Path) -> Path:
        self.turn_index += 1
        return out_dir / f"reply-{self.turn_index:03d}.mp3"


class AudioInputTransport(Protocol):
    def read_user_audio_path(self) -> Path | None:
        """Return the next user audio path, or None when the session should end."""


class AudioOutputTransport(Protocol):
    def publish_audio(self, audio_path: Path) -> None:
        """Publish or play an audio artifact."""


class TerminalFileInputTransport:
    """No-hardware substitute for a microphone.

    The user types a local audio path such as samples/demo.wav. Future hardware
    transports can replace this with WebSocket audio frames.
    """

    def read_user_audio_path(self) -> Path | None:
        try:
            raw = input("请输入用户语音文件路径，或输入 exit 退出: ").strip()
        except EOFError:
            return None
        if not raw or raw.lower() in {"exit", "quit", "q"}:
            return None
        return Path(raw)


class FileAudioOutputTransport:
    """No-hardware substitute for a speaker."""

    def __init__(self, play: bool = False) -> None:
        self.play = play

    def publish_audio(self, audio_path: Path) -> None:
        print(f"AUDIO_OUTPUT={audio_path}")
        if not self.play:
            return
        player = shutil.which("ffplay")
        if not player:
            print("WARN=ffplay not found; skip playback")
            return
        subprocess.run(
            [player, "-nodisp", "-autoexit", str(audio_path)],
            check=False,
        )
