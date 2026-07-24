# Spec: 陪伴点展示换皮（账本仍为分钟）

**日期：** 2026-07-24  
**状态：** 待实现  
**关联：** [`docs/PRICING_STRATEGY.md`](../../PRICING_STRATEGY.md)、文字计费 [`src/shuxin/voice/billing/text_billing.py`](../../../src/shuxin/voice/billing/text_billing.py)、额度门控 [`docs/VOICE_QUOTA_GATE_TEST.md`](../../VOICE_QUOTA_GATE_TEST.md)

## 目标

语音与文字共用同一额度账本后，用户侧再显示「分钟」不自然。引入用户可见单位 **陪伴点**，统一「聊天在消耗同一货币」的心智；**不改变**底层扣费与门控。

成功判据：小程序余额、聊天/伙伴额度提示、充值套餐描述、额度耗尽等用户可见文案均使用「陪伴点」；同等操作下实际扣减的分钟数与改前一致。

## 已定决策

| 项 | 决策 |
|----|------|
| 改动层级 | **展示层换皮（方案 A）**；账本仍为分钟 |
| 用户单位名 | **陪伴点** |
| 换算 | **1 分钟 = 10 陪伴点**（`POINTS_PER_MINUTE = 10`） |
| 实现路径 | **前端换算 + 服务端用户文案统一（方案 2）**；API 字段名暂不改 |
| 覆盖范围 | **小程序 + 返回给用户的中文错误/提示**；不改硬件提示音资源、不改 Admin 内部用语 |
| 非目标 | 不迁移 DB 字段；不新增 `remain_points` API 字段（本期）；不恢复静默拉微信资料之类无关能力 |

## 产品规则

- **余额展示**：`points = round(minutes × 10)`，默认整数。若 `minutes > 0` 且取整后为 0，显示 `1`（避免有额度却显示 0）。
- **文字预估**：分钟预估 ×10 后显示整数「约 N 陪伴点」（可去掉「实扣按 token」对用户的技术措辞，或改为「实际按用量结算」）。
- **充值套餐**：对外「含 xxx 陪伴点」；库内 `duration_minutes` 不变，展示时 ×10。
- **耗尽**：用户可见文案统一为「陪伴点已用尽，请充值」一类；不再对用户说「分钟」。
- **心智一句话**：语音/文字聊天花的都是陪伴点；后台仍按分钟记账。

## 架构与数据流

```text
扣费/门控 (minutes) → devices 等账本 remain_*（分钟语义）
                         ↓
              × POINTS_PER_MINUTE (仅展示)
                         ↓
              用户可见：陪伴点（小程序 UI + 用户向 message）
```

- 字段如 `remain_yuan` **语义仍为分钟等价额度**（历史命名），客户端与文档注明「展示前 ×10」。
- 服务端用户向字符串集中替换；内部日志/Admin 可继续写分钟。

## 组件与触点

### 小程序

- 新增 `apps/wechat-miniprogram/src/utils/companion-points.ts`：`POINTS_PER_MINUTE`、`minutesToPoints`、`formatPointsLabel`。
- [`useProfile.ts`](../../../apps/wechat-miniprogram/src/modules/account/composables/useProfile.ts)：`balanceLabel` → 陪伴点；个人中心标签改为「账户剩余陪伴点」。
- [`chat.vue`](../../../apps/wechat-miniprogram/src/pages/chat/chat.vue)、[`partners.vue`](../../../apps/wechat-miniprogram/src/pages/partners/partners.vue)：低保/可用/打字预估文案去「分钟」。
- 充值 sheet：对套餐 `description` / 时长展示做 ×10 与「陪伴点」后缀（若后端已返回陪伴点文案则直接显示）。

### 服务端（用户可见文案）

- [`QUOTA_EXHAUSTED_MESSAGE`](../../../src/shuxin/voice/integrations/dmx_client.py) → 「陪伴点已用尽，请充值」。
- [`billing_repo.py`](../../../src/shuxin/voice/persistence/billing_repo.py) 套餐默认 description：由 `N分钟` 改为 `N×10 陪伴点`（或「含 M 陪伴点」）。
- 扫描并替换其它返回给小程序/用户的 quota 相关 `message` 中的「分钟」额度表述。
- 可选：共享常量模块（如 `voice/billing/companion_points.py`）仅用于格式化用户文案，**禁止**改 `deduct_device_minutes_quota` 入参语义。

### 明确不改

- `deduct_device_minutes_quota`、额度门控、Postgres 额度字段。
- 硬件 `QUOTA_EXHAUSTED` 音频资源。
- Admin 运营看板内部「分钟」表述（除非顺手且无风险，本期不做）。

## 错误处理

- 展示换算失败（空/NaN）：显示「—」或「查询失败」，与现网一致。
- 若服务端仍返回含「分钟」的旧缓存文案：以客户端二次替换为兜底（仅额度相关短句），长期以后端文案为准。

## 测试与验收

1. 个人中心余额为原分钟 ×10 的陪伴点整数展示。
2. 聊天页、伙伴页额度文案无「分钟」。
3. 文字发送预估为「约 N 陪伴点」。
4. 充值套餐用户可见描述为陪伴点。
5. 额度耗尽错误/提示为陪伴点表述（含 `QUOTA_EXHAUSTED_MESSAGE` 断言更新）。
6. 同等输入下扣费分钟数与改前一致（回归现有 quota/text billing 测试）。
7. `bash scripts/wechat_miniprogram_dev.sh build` 通过。

## 文档

- 在 [`docs/WECHAT_MINIPROGRAM.md`](../../WECHAT_MINIPROGRAM.md) 或定价相关文档加一句：用户侧单位为陪伴点，1 分钟 = 10 陪伴点，账本仍为分钟。
