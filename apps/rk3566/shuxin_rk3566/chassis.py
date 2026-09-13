"""Chassis backends for voice-driven movement.

The first cut does not assume a specific motor HAT. Default is a safe mock
that logs commands. A real car can be wired by:

- SHUXIN_CHASSIS=cmd and SHUXIN_CHASSIS_CMD, or
- implementing ChassisDriver.execute / stop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
from typing import Protocol

from shuxin_rk3566.motion_intent import MotionCommand

logger = logging.getLogger("shuxin.rk3566.chassis")


class ChassisDriver(Protocol):
    async def execute(self, command: MotionCommand) -> None: ...

    async def stop(self) -> None: ...


class MotionController:
    """Serialize motion so a new command (especially stop) cancels the previous one."""

    def __init__(self, driver: ChassisDriver) -> None:
        self._driver = driver
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self.last_command: MotionCommand | None = None

    async def handle(self, command: MotionCommand) -> None:
        self.last_command = command
        async with self._lock:
            if self._task is not None and not self._task.done():
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception("previous motion failed during cancel")
            if command.is_stop:
                await self._driver.stop()
                return
            self._task = asyncio.create_task(self._driver.execute(command), name="rk3566-motion")

    async def close(self) -> None:
        await self.handle(
            MotionCommand(action="stop", duration_s=0.0, speed=0.0, source_text="shutdown")
        )


class MockChassis:
    """Dev/PC backend: log and wait, no GPIO."""

    def __init__(self) -> None:
        self.history: list[MotionCommand] = []

    async def execute(self, command: MotionCommand) -> None:
        self.history.append(command)
        logger.info(
            "chassis %s duration=%.2fs speed=%.2f text=%s",
            command.action,
            command.duration_s,
            command.speed,
            command.source_text,
        )
        if command.duration_s > 0:
            await asyncio.sleep(command.duration_s)
        logger.info("chassis idle after %s", command.action)

    async def stop(self) -> None:
        logger.info("chassis STOP")


class CommandChassis:
    """Call an external motor script: {action} {duration_s} {speed}."""

    def __init__(self, template: str) -> None:
        if not template.strip():
            raise ValueError("chassis command template is empty")
        self.template = template

    def _argv(self, command: MotionCommand) -> list[str]:
        rendered = (
            self.template.replace("{action}", command.action)
            .replace("{duration}", f"{command.duration_s:.2f}")
            .replace("{speed}", f"{command.speed:.2f}")
        )
        return shlex.split(rendered, posix=os.name != "nt")

    async def execute(self, command: MotionCommand) -> None:
        argv = self._argv(command)
        logger.info("chassis cmd %s", argv)
        proc = await asyncio.create_subprocess_exec(*argv)
        try:
            await proc.wait()
        except asyncio.CancelledError:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=1.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                proc.kill()
            raise
        if proc.returncode not in (0, None):
            logger.warning("chassis command exited %s", proc.returncode)

    async def stop(self) -> None:
        await self.execute(
            MotionCommand(action="stop", duration_s=0.0, speed=0.0, source_text="stop")
        )


def build_chassis(kind: str | None = None, command: str | None = None) -> ChassisDriver:
    selected = (kind or os.environ.get("SHUXIN_CHASSIS") or "mock").strip().lower()
    if selected in {"cmd", "command", "script"}:
        template = (command or os.environ.get("SHUXIN_CHASSIS_CMD") or "").strip()
        return CommandChassis(template)
    return MockChassis()
