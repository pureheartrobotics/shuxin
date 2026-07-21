# Spec: 初心最小商城 V1

## Objective

设备周边实体店：同一小程序登录与微信支付下，用户可浏览多 SKU 商品、下单、查看物流号；运营在 `/miniapp-admin` 管理商品与发货。

## Tech Stack

- Backend: FastAPI + Postgres（`services/mall`、`persistence/mall_repo`）
- Mini-program: uni-app Vue3 `<script setup lang="ts">`（`modules/mall`）
- Ops UI: `/miniapp-admin`（Vue3 CDN，`miniapp_admin.html`）
- Pay: 现有 `WeChatPayGateway`，`out_trade_no` 前缀 `mx`

## Commands

```bash
bash scripts/wechat_miniprogram_dev.sh build
pytest tests/test_mall_api.py tests/test_mall_migration.py tests/test_miniapp_admin_auth.py tests/test_wechat_miniprogram_scaffold.py -q
```

## Project Structure

- `src/shuxin/voice/api/routers/mall.py` — 用户 API
- `src/shuxin/voice/api/miniapp_admin.py` — 运营 API（含 mall）
- `src/shuxin/voice/persistence/mall_repo.py` — 领域持久化
- `apps/wechat-miniprogram/src/modules/mall/` — 小程序商城
- `src/shuxin/voice/static/miniapp_admin.html` — 运营台 UI

## Boundaries

- Always: 金额用分；鉴权失败 401/403；改小程序后 build
- Ask first: 退款、第三方物流、OSS、删 `/admin` mall 路由
- Never: fork Java 开源整仓；第二套用户/商户；提交密钥

## Success Criteria

- miniapp-admin 无配置 Token 时无法登录（无硬编码默认值）
- 套餐定价下有商城管理（多 SKU + 发货 carrier/运单号）
- Tab：设备 | 商城 | 我的；规格选购、地址 CRUD、订单见物流
- 未支付取消/超时释放库存；支付成功不重复扣库存

## Architecture Decision

同仓加固；否决外挂 Java 开源商城（单人、同账号同支付、周边店场景）。
