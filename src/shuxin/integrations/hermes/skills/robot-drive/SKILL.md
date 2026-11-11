---
name: robot-drive
description: 驱动陪伴机器人底盘前进、后退、左转、右转或立刻停车。用户说走、过来、倒车、转弯、停下时使用。
---

# 底盘

用工具 `robot_drive`，不要假装已经走动。

- `action`: `forward` / `back` / `left` / `right` / `stop`
- `duration`: 秒，默认 1.5，最多 4；用户说「一点」用 0.8
- `speed`: 0.35 慢，0.55 默认，0.85 快

停必须立刻 `stop`。连续换方向前先停。没有底盘工具时诚实说轮子现在动不了。
