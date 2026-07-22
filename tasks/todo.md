# Todo: 投资人版抽卡小程序

Spec: `docs/2026-07-22-investor-miniprogram-gacha-chat-design.md`  
Plan: `tasks/plan.md`  
**实现前门禁：人工批准本 Spec/Todo。**

- [ ] Task: 开分支 `feat/investor-miniprogram-gacha-chat`
  - Acceptance: 分支存在且基于约定基线
  - Verify: `git branch --show-current`
  - Files: n/a

- [ ] Task: Migration — `user_companions` + gacha/text_billing settings 种子
  - Acceptance: 表可写；settings 可读默认价 9.9、免费 3、LLM 单价
  - Verify: migration up；pytest 读 settings
  - Files: `src/shuxin/voice/migrations/*`, settings helpers

- [ ] Task: Soft device 懒创建 + `POST /api/voice/soft-credentials`
  - Acceptance: 每用户仅 1 台 soft；硬件列表不含 soft；返回 device_id+secret
  - Verify: 单测双次调用仍一台；list devices 过滤
  - Files: device/user repo, user router

- [ ] Task: Companions list/rename API
  - Acceptance: 仅本人；改名持久化
  - Verify: TestClient
  - Files: companions repo + router

- [ ] Task: Gacha config + free draw（加权、扣免费次数、入库）
  - Acceptance: 服务端出 mbti；免费次数减一；可重复类型
  - Verify: `tests/test_gacha_*.py`
  - Files: gacha module + router

- [ ] Task: Gacha 付费下单 + draw 核销 payment_id
  - Acceptance: 未支付不可抽；同一 payment 仅一次
  - Verify: 单测 mock 支付状态
  - Files: gacha orders + payment glue

- [ ] Task: `text_billing` 模块 + `POST /api/chat/text`
  - Acceptance: 超 500 拒；只按 LLM usage 折分钟并 deduct；模块可单测替换汇率
  - Verify: `tests/test_text_billing.py`
  - Files: `billing/text_billing.py`, chat router

- [ ] Task: Voice WS 接受 companion_id（soft 会话切 MBTI/记忆）
  - Acceptance: 不同 companion 人格/记忆目录隔离；主循环不改扣减顺序
  - Verify: 单测或脚本断言 metadata/mbti 应用
  - Files: `ws_session.py`（小改）

- [ ] Task: miniapp-admin 投资人指标 API + 看板 Tab
  - Acceptance: 注册/抽卡/转化/伙伴数/文字轮次/语音轮次可见
  - Verify: `tests/test_investor_metrics.py`；HTML 含 Tab
  - Files: `miniapp_admin.py`, `miniapp_admin.html`

- [ ] Task: miniapp-admin 抽卡价格与 weights 编辑
  - Acceptance: 保存后 `/api/gacha/config` 反映新值
  - Verify: API 往返测试
  - Files: miniapp_admin + settings

- [ ] Task: 小程序 Tab 伙伴|抽卡|我的 + 老虎机 + 聊天 UI
  - Acceptance: 无硬件可完成抽卡与文字/语音；动画对齐服务端 mbti
  - Verify: `bash scripts/wechat_miniprogram_dev.sh build`
  - Files: `apps/wechat-miniprogram/**`

- [ ] Task: 投资人演示验收清单（docs 短节）
  - Acceptance: 逐步操作与看板对照说明
  - Verify: 文档可读
  - Files: design doc 附录或 `docs/VOICE_DEMO_*` 短节
