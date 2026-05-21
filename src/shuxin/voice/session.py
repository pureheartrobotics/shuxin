from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from shuxin.core.agent import Agent
from shuxin.voice.providers import create_stt_provider, create_tts_provider
from shuxin.voice.service import VoiceService
from shuxin.voice.transport import (
    AudioInputTransport,
    AudioOutputTransport,
    DeviceSession,
    FileAudioOutputTransport,
    TerminalFileInputTransport,
)


class VoiceSessionRunner:
    """No-hardware voice loop for one device session."""

    def __init__(
        self,
        service: VoiceService,
        device_id: str | None = None,
        out_dir: Path = Path("outputs/session"),
        welcome_text: str = "你好，我是舒心，我们开始聊天吧。",
        input_transport: AudioInputTransport | None = None,
        output_transport: AudioOutputTransport | None = None,
        max_turns: int | None = None,
    ) -> None:
        self.service = service
        self.device = service.device_provider.get(device_id)
        self.runtime = DeviceSession(device_id=self.device.device_id)
        self.out_dir = out_dir
        self.welcome_text = welcome_text
        self.input_transport = input_transport or TerminalFileInputTransport()
        self.output_transport = output_transport or FileAudioOutputTransport()
        self.max_turns = max_turns

    async def run(self) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = self.out_dir / "transcript.txt"
        stt = create_stt_provider(self.device.stt)
        tts = create_tts_provider(self.device.tts)
        agent = self.service.create_agent(self.device)

        agent.initialize()
        try:
            init_audio = await tts.synthesize(
                self.welcome_text,
                self.out_dir / "init.mp3",
            )
            self.output_transport.publish_audio(init_audio)
            self._start_transcript(transcript_path, init_audio)

            if self.max_turns == 0:
                print(f"TRANSCRIPT={transcript_path}")
                return transcript_path

            while self.max_turns is None or self.runtime.turn_index < self.max_turns:
                user_audio = self.input_transport.read_user_audio_path()
                if user_audio is None:
                    break

                user_audio = user_audio.expanduser()
                if not user_audio.exists():
                    print(f"WARN=audio file not found: {user_audio}")
                    continue

                print(f"USER_AUDIO={user_audio}")
                user_text = await stt.transcribe(user_audio)
                print(f"USER_TEXT={user_text}")

                reply_text = await asyncio.to_thread(agent.chat, user_text)
                reply_text = reply_text.strip()
                print(f"AGENT_REPLY={reply_text}")

                reply_audio = await tts.synthesize(
                    reply_text,
                    self.runtime.next_reply_path(self.out_dir),
                )
                self.output_transport.publish_audio(reply_audio)
                print(f"REPLY_AUDIO={reply_audio}")

                self._append_turn(
                    transcript_path,
                    user_audio=user_audio,
                    user_text=user_text,
                    reply_text=reply_text,
                    reply_audio=reply_audio,
                )

            print(f"TRANSCRIPT={transcript_path}")
            return transcript_path
        finally:
            agent.shutdown()

    def _start_transcript(self, transcript_path: Path, init_audio: Path) -> None:
        content = [
            "# ShuXin Voice Session",
            "",
            f"started_at={datetime.now().isoformat(timespec='seconds')}",
            f"device_id={self.runtime.device_id}",
            f"client_id={self.runtime.client_id}",
            f"init_audio={init_audio}",
            f"init_text={self.welcome_text}",
            "",
        ]
        transcript_path.write_text("\n".join(content), encoding="utf-8")

    def _append_turn(
        self,
        transcript_path: Path,
        user_audio: Path,
        user_text: str,
        reply_text: str,
        reply_audio: Path,
    ) -> None:
        lines = [
            f"## Turn {self.runtime.turn_index:03d}",
            "",
            f"user_audio={user_audio}",
            f"user_text={user_text}",
            f"reply_audio={reply_audio}",
            f"reply_text={reply_text}",
            "",
        ]
        with transcript_path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
