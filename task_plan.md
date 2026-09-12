# 任务计划：语音测试台自动重连与连接鉴权门禁实现

## 目标
实现前端切换目标设备时自动重新连接 WebSocket，以及后端对未鉴权 WebSocket 消息（针对 `listen` 和 `text_turn`）的安全拦截门禁，彻底解决设备切换状态不一致及隐式兜底至 `demo-user` 导致报错的问题。

## 当前阶段
阶段 5

## 各阶段

### 阶段 1：需求与发现
- [x] 理解用户关于 o0Gl... SX-000131 等非 demo 设备连接时依然报错的意图
- [x] 确定缓存失效、UI 状态不一致、后端兜底机制等约束条件
- [x] 将发现记录到 findings.md
- **状态：** complete

### 阶段 2：规划与结构
- [x] 确定前端通过切换下拉框自动触发重新建连的技术方案
- [x] 确定后端在 _handle_text 统一做鉴权门禁拦截的技术方案
- [x] 记录决策及理由并撰写 Spec [2026-07-01-voice-demo-reconnect-auth-gate-design.md](file:///home/peter/huada/project/Interesting/codex_agent/shuxin/docs/superpowers/specs/2026-07-01-voice-demo-reconnect-auth-gate-design.md)
- **状态：** complete

### 阶段 3：实现
- [x] 修改 `src/shuxin/voice/server.py` 内的 `_web_demo_html` JavaScript，实现自动重连
- [x] 修改 `src/shuxin/voice/server.py` 的 `_handle_text` 逻辑，实现后端安全鉴权门禁
- **状态：** complete

### 阶段 4：测试与验证
- [x] 编写针对 `_VoiceWebSocketSession._handle_text` 的自动化测试，验证拦截功能
- [x] 使用 `scripts/redeploy_docker.sh` 重新部署服务并进行人工功能联调
- [x] 将测试结果记录到 progress.md
- **状态：** complete

### 阶段 5：交付
- [ ] 检查所有输出文件，确保没有多余的临时文件残留
- [ ] 确保代码风格与项目现有架构（Hermes 标准）一致
- [ ] 交付给用户
- **状态：** in_progress

## 关键问题
1. 前端切换自动触发 ws.close() 时，是否需要延时 150ms 触发 connectBtn.click() 以确保旧连接完全关闭？（设计已确认：需要，且设为 150ms 延时最为安全健壮）
2. 后端拦截未鉴权对话时，是否会影响正常的 ping 保活消息？（设计已确认：ping 消息不作拦截，仅拦截 `listen` 和 `text_turn`）

## 已做决策
| 决策 | 理由 |
|------|------|
| 同时进行前端重连和后端拦截 | 单纯前端重连解决的是好用的问题，后端拦截解决的是兜底导致的误导报错和接口安全问题，二者结合最健壮。 |

## 遇到的错误
| 错误 | 尝试次数 | 解决方案 |
|------|---------|---------|
| git add 被 ignore 阻挡 | 1 | 对放在被过滤文件夹 `docs/superpowers/specs/` 下的设计文档，改用 `git add -f` 强制提交。 |
