"""Parse spoken Chinese into a chassis motion command.

Voice movement is handled on-device from STT text so the car can start
moving before the companion LLM finishes talking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ACTIONS = ("stop", "forward", "backward", "left", "right", "spin")

DEFAULT_MOVE_SECONDS = 1.5
NUDGE_SECONDS = 0.8
LONG_SECONDS = 2.5
MAX_MOVE_SECONDS = 4.0
DEFAULT_SPEED = 0.55
SLOW_SPEED = 0.35
FAST_SPEED = 0.85

_STOP_RE = re.compile(
    r"(停下|停车|停止|站住|别动|不要动|不要走|不要往|别往前|取消|停一下|^停$|^停[，,。！! ])"
)
_SPIN_RE = re.compile(r"(转一圈|转圈|原地转|掉头|调头)")
_BACK_RE = re.compile(r"(后退|往后|向后|倒车|退后)")
_LEFT_RE = re.compile(r"(左转|向左转|往左转|向左|往左)")
_RIGHT_RE = re.compile(r"(右转|向右转|往右转|向右|往右)")
_FORWARD_RE = re.compile(r"(前进|往前|向前走|向前|过来|走近|走过来|开过来)")

_NUDGE_RE = re.compile(r"(一点点|一点|一下|稍微|慢点走)")
_LONG_RE = re.compile(r"(远一点|久一点|多走|一直)")
_SLOW_RE = re.compile(r"(慢|缓缓)")
_FAST_RE = re.compile(r"(快|赶紧)")
_SECONDS_RE = re.compile(r"([一二三四五六七八九十两\d]+)\s*秒")

_CN_NUM = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


@dataclass(frozen=True)
class MotionCommand:
    action: str
    duration_s: float
    speed: float
    source_text: str

    @property
    def is_stop(self) -> bool:
        return self.action == "stop"


def _parse_seconds(token: str) -> float:
    token = token.strip()
    if token.isdigit():
        return float(token)
    return float(_CN_NUM.get(token, 0) or 0)


def _duration_and_speed(text: str, *, is_stop: bool) -> tuple[float, float]:
    if is_stop:
        return 0.0, 0.0
    duration = DEFAULT_MOVE_SECONDS
    speed = DEFAULT_SPEED
    match = _SECONDS_RE.search(text)
    if match:
        parsed = _parse_seconds(match.group(1))
        if parsed > 0:
            duration = min(parsed, MAX_MOVE_SECONDS)
    elif _NUDGE_RE.search(text):
        duration = NUDGE_SECONDS
    elif _LONG_RE.search(text):
        duration = LONG_SECONDS
    if _FAST_RE.search(text):
        speed = FAST_SPEED
    elif _SLOW_RE.search(text):
        speed = SLOW_SPEED
    return duration, speed


def parse_motion_intent(text: str) -> MotionCommand | None:
    """Return a motion command when the utterance is clearly a drive order."""
    raw = (text or "").strip()
    if not raw:
        return None
    compact = re.sub(r"\s+", "", raw)

    if _STOP_RE.search(compact):
        duration, speed = _duration_and_speed(compact, is_stop=True)
        return MotionCommand("stop", duration, speed, raw)
    if _SPIN_RE.search(compact):
        duration, speed = _duration_and_speed(compact, is_stop=False)
        return MotionCommand("spin", max(duration, 1.2), speed, raw)
    if _BACK_RE.search(compact):
        duration, speed = _duration_and_speed(compact, is_stop=False)
        return MotionCommand("backward", duration, speed, raw)
    if _LEFT_RE.search(compact):
        duration, speed = _duration_and_speed(compact, is_stop=False)
        return MotionCommand("left", min(duration, 2.0), speed, raw)
    if _RIGHT_RE.search(compact):
        duration, speed = _duration_and_speed(compact, is_stop=False)
        return MotionCommand("right", min(duration, 2.0), speed, raw)
    if _FORWARD_RE.search(compact):
        duration, speed = _duration_and_speed(compact, is_stop=False)
        return MotionCommand("forward", duration, speed, raw)
    return None
