---
name: robot-head
description: 控制机器人头部点头、摇头，或转到指定角度。用户说点头、摇头、转头、看看左边时使用。
---

# 转头

用工具 `robot_head`，不要只在括号里写动作却不调用。

- `action`: `nod` 点头，`shake` 摇头，`center` 回正，`turn` 转到角度
- `turn` 时 `pan` 左右 0–180（90 正前方，小于 90 左转，大于 90 右转）
- `tilt` 上下 0–180（90 水平，小于 90 抬头，大于 90 低头）

点头摇头用 `nod`/`shake`。要看某一侧再用 `turn`。环顾四周请用 `robot_look_around`，不要自己连发一串 turn。
