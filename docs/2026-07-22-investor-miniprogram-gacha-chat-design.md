# Spec: 投资人版小程序 — 抽卡伙伴 + 对话 + 增长看板

**日期：** 2026-07-22  
**计划分支：** `feat/investor-miniprogram-gacha-chat`（自 `improve-codebase`）  
**状态：** 待人工批准后实现（SPECIFY 完成；PLAN/TASKS 见 `tasks/`）  
**关联设计决策：** 增长证明选 B（看板）；看板挂 `/miniapp-admin`；语音鉴权选 A（soft-credentials）

## Objective

向投资人证明产品**有市场、有人数**：无硬件可获客、可抽卡、可对话、可付费；运营台能展示注册/抽卡/转化/对话等数字。

**用户：** 微信小程序终端用户；演示讲解人用 `/miniapp-admin`。  
**长期：** 本线可弃；硬件绑定产品为主路径，不被 soft/companion 污染。

## Tech Stack

- Python 3.11+ / FastAPI / Postgres（现有 voice 栈）
- 微信小程序 uni-app（`apps/wechat-miniprogram`）
- 微信支付（复用现有小程序支付）
- Voice WebSocket（现有 STT→LLM→TTS；soft device 凭证）
- 运营台：[`src/shuxin/voice/static/miniapp_admin.html`](src/shuxin/voice/static/miniapp_admin.html) + [`miniapp_admin.py`](src/shuxin/voice/api/miniapp_admin.py)

## Commands

```bash
# 分支
git checkout -b feat/investor-miniprogram-gacha-chat

# 测试（实现过程中按模块追加）
pytest tests/test_gacha_*.py tests/test_companions_*.py tests/test_text_billing.py tests/test_investor_metrics.py -q

# 小程序
bash scripts/wechat_miniprogram_dev.sh build
# 微信工具导入 dist/build/mp-weixin

# 部署（env/迁移后）
bash scripts/redeploy_docker.sh
```

## Project Structure

```text
docs/2026-07-22-investor-miniprogram-gacha-chat-design.md  → 本 Spec（活文档）
tasks/plan.md / tasks/todo.md                             → 实现计划与任务
src/shuxin/voice/migrations/                              → user_companions 等
src/shuxin/voice/persistence/                             → companions / gacha repo
src/shuxin/voice/billing/text_billing.py                  → 可替换文字计费
src/shuxin/voice/api/routers/                             → gacha / companions / chat text
src/shuxin/voice/api/miniapp_admin.py                     → 指标 + gacha 配置 API
src/shuxin/voice/static/miniapp_admin.html                → 「投资人数据」「抽卡配置」Tab
apps/wechat-miniprogram/src/                              → Tab 伙伴|抽卡|我的 + 聊天
tests/                                                    → 抽卡/计费/指标单测
```

## Code Style

```python
# 文字计费必须隔离：路由不内联汇率
from shuxin.voice.billing.text_billing import (
    estimate_minutes_for_text,
    minutes_from_llm_usage,
)

minutes = minutes_from_llm_usage(usage, settings)
await billing_repo.deduct_device_minutes_quota(soft_device_id, minutes)
```

- 命名：`user_companions`、`free_gacha_remaining`、`kind=soft`
- 硬件列表 API **过滤** soft device
- 抽卡结果仅服务端权威；小程序动画对齐返回的 `mbti`
- Pydantic/路由类型：宿主机若需兼容，避免裸 `int | None`（沿用项目既有约定）

## Testing Strategy

| 层级 | 覆盖 |
|------|------|
| 单测 | 加权抽卡；免费扣次；payment 单次核销；text estimate/actual；metrics 聚合；soft 过滤 |
| 集成 | TestClient：gacha draw、companions list、miniapp-admin metrics 需登录 |
| 手工 | 注册→抽3→付费抽→文字→语音→看板数字变化 |

覆盖率不设硬指标；关键路径必须有断言。

## Boundaries

- **Always：** 服务端权威抽卡；文字计费单模块；看板在 miniapp-admin；soft 凭证接口；跑相关 pytest；小程序改完 build
- **Ask first：** 改语音分钟主公式；邀请裂变；把 companion 并进 devices 业务主键；删硬件 bind
- **Never：** 提交密钥；信任客户端 MBTI；在硬件「我的设备」展示 soft；重写 Voice 主循环

## 产品决策（锁定）

| 项 | 决策 |
|----|------|
| 伙伴 | 纯软件；表 `user_companions`（可弃） |
| 免费 | 3 次抽卡机会；重复类型也扣次；可多同 MBTI |
| 付费 | 先付后抽；默认 ¥9.9；权重后台可配 |
| Tab | 伙伴 \| 抽卡 \| 我的 |
| 语音 | soft-credentials 签发 → 现有 WS；`companion_id` 切人格 |
| Soft device | 每用户 1 台 |
| 文字 | 只计 LLM；折算分钟可替换；默认 500 字 |
| 看板 | `/miniapp-admin`；证明有人数 |
| 指标 | 优先表聚合，不建重型事件中台 |

## 增长指标（看板必出）

- 注册用户数  
- 免费抽次数 / 付费抽次数  
- 付费抽转化率（付费抽过的用户 / 免费次数用尽的用户）  
- 伙伴总数  
- 文字对话轮次  
- 语音对话轮次（soft device / user 聚合现有 usage）  
- DAU 或近 7 日活跃（登录或抽卡/对话去重，实现时取易算口径并在看板标注）

## Success Criteria

1. 无硬件完成：登录 → 抽卡 → 文字聊 → 语音聊 → 付费再抽  
2. `/miniapp-admin` 可看到上表指标且随操作变化  
3. 可改抽卡价格与 weights  
4. 文字计费改配置/模块即可换公式，无需改 Agent 主路径  
5. 真硬件 bind / Voice 主循环行为回归不受损（既有测试仍绿）

## 附录 A：投资人演示清单

1. 小程序登录 → Tab「抽卡」→ 免费摇 1～3 次 → 进「伙伴」列表  
2. 点伙伴 → 文字聊天（≤500 字）→ `/miniapp-admin`「投资人数据」看注册/抽卡/文字轮次增加  
3. `SHUXIN_WECHAT_MOCK=1` 时付费抽自动记已支付；正式环境走微信收银台  
4. 语音：聊天页会拉取 soft-credentials；WS hello 带 `device_id/secret` + `companion_id`  
5. 看板改抽卡价格/权重后，小程序 `/api/gacha/config` 应反映新值  


## Soft credentials 流程

```text
登录后 → POST /api/voice/soft-credentials
  → 确保每用户 1 台 soft device（明文 secret 仅此时返回）
  → 小程序本地保存 → Voice WS hello 用 device_id+secret
  → 回合带 companion_id
```
