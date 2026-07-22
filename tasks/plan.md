# Plan: 投资人版抽卡小程序 + miniapp-admin 看板

## North star

投资人相信「有市场、有人数」= **可玩闭环** + **`/miniapp-admin` 数字看板**。

Spec：[`docs/2026-07-22-investor-miniprogram-gacha-chat-design.md`](../docs/2026-07-22-investor-miniprogram-gacha-chat-design.md)

## 依赖顺序

```text
migration + settings
    → companions + soft device + soft-credentials
        → gacha (free/paid)     ──┐
        → text chat + text_billing ─┼→ miniprogram UI
        → WS companion_id        ──┘
    → miniapp-admin metrics + gacha config UI
    → tests + 演示清单
```

垂直切片建议：先「抽卡入库 + 列表」→「文字聊」→「语音」→「付费抽」→「看板」。

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| Soft secret 泄漏 | 仅签发接口返回一次；存储 hash；HTTPS |
| 指标口径扯皮 | 看板标注公式；优先 SQL 聚合 companions/支付/usage |
| 小程序 Tab 动商城 | 商城入口放「我的」，不删 mall 模块 |
| 范围膨胀 | 不做裂变；不改 Voice 主循环 |

## 验证检查点

1. Migration 后 companions CRUD + soft-credentials 单测绿  
2. 免费抽 3 次 + 列表可见  
3. 文字聊扣分钟 + 超 500 字拒绝  
4. WS + companion_id 能出语音回复  
5. 付费抽核销一次  
6. miniapp-admin 指标随操作变化  
