# 发现与决策

## 需求
- 当用户在测试页面的下拉框选择新设备时，应自动进行 WebSocket 断开和重连，使连接更新。
- 后端需要对未通过 `hello` 进行鉴权的连接进行对话功能限制，避免隐式兜底至 `demo-user` 导致发生误导用户的 LLM 密钥未配置报错。

## 研究发现
- `o0GlJ3bR8mxfS3qz7JKF0T5aRZUM` 的 LLM 配置在数据库中事实上是完全正确配置的，并不存在缺失 DMX API Key 的问题。
- Uvicorn 中的设备鉴权信息存在 5 分钟的内存缓存 `_auth_cache`，这导致如果在 DMX 配置前有一次未成功的建连，其后的重连即便数据库有数据也会命中缓存。
- 前端测试台的 `testTargetSelect.onchange` 仅修改文本框的值，不主动重连，导致后续的对话还是发往已经握手完毕的旧会话设备（默认为默认种子 `demo-device-001`）。

## 技术决策
| 决策 | 理由 |
|------|------|
| 150ms 前端重连延时 | 在调用 `ws.close()` 关闭当前 WebSocket 之后，浏览器需要极短的时间清理连接套接字。延时 150ms 触发 `connectBtn.click()` 可以有效规避“旧连接尚未断开新连接已被旧连接关闭”的并发竞态问题。 |
| 后端鉴权前置拦截门禁 | 在后端 `_handle_text` 的起始部分针对 `listen` 和 `text_turn` 进行 `self.user_settings` 判断，是侵入性最小、防护最安全的门禁。 |

## 遇到的问题
| 问题 | 解决方案 |
|------|---------|
| 无法直接使用 `git add` 暂存 docs/superpowers 路径 | 使用 `git add -f` 强制暂存并成功 Commit。 |
| 并发任务中的 get_device() 覆盖 self.device 造成 API Key 被清空 | 改用局部变量读取设备配置进行 MBTI 揭晓状态逻辑判断，禁止对实例变量 self.device 重新覆盖赋值，彻底隔离并发竞态影响。 |

## 资源
- 说明书路径：[docs/superpowers/specs/2026-07-01-voice-demo-reconnect-auth-gate-design.md](file:///home/peter/huada/project/Interesting/codex_agent/shuxin/docs/superpowers/specs/2026-07-01-voice-demo-reconnect-auth-gate-design.md)
