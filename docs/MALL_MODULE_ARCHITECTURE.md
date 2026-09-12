# 微信小程序商城模块架构

## 模块边界

初心小程序 = **一个 App、三个业务模块**，共享登录与 HTTP 基建：

| 模块 | 目录 | 职责 |
|------|------|------|
| Device | `modules/device/` | 设备绑定、BLE 配网、工厂 QA |
| Mall | `modules/mall/` | 实体商品浏览、购物车、下单、物流号 |
| Account | `modules/account/` | 登录态、个人中心、**时长充值（保持 profile 弹窗）** |

横切：`core/http.ts`、`core/auth.ts`

规格见 [`docs/specs/mall-v1.md`](specs/mall-v1.md)。

## 前端分层

```
Page → modules/*/api → core/http → 后端 API
```

禁止：页面内联 `uni.request`、单文件 500+ 行业务逻辑。

## 后端分层

```
Router → Service → Repository → Postgres
         ↘ Gateway (微信支付)
```

| 层 | 路径 | 职责 |
|----|------|------|
| Router | `api/routers/mall.py`、`api/miniapp_admin.py` | 参数校验、HTTP 响应 |
| Service | `services/mall/`、`services/payment/` | 业务编排 |
| Repository | `persistence/mall_repo.py` | CRUD / 库存预占 |
| Gateway | `services/payment/wechat_pay_gateway.py` | 微信 SDK 封装 |

## 支付分离

- **QuotaPaymentService**：时长充值，`payment_orders` 表，profile 弹窗流程不变
- **MallPaymentService**：实体商品，`mall_orders` 表，`out_trade_no` 前缀 `mx`
- 共用 `WeChatPayGateway`；notify 按 `out_trade_no` 前缀路由

## 库存语义

- 创建订单：扣减 `mall_skus.stock`（预占），清空购物车，订单 `pending`
- 支付成功：仅改 `paid`（不再扣库存）
- 用户取消 / 超时（`SHUXIN_MALL_PENDING_EXPIRE_MINUTES`，默认 30）：`cancelled` 并回补库存

## 运营后台

- 主入口：`/miniapp-admin` → 侧栏「商城管理」（套餐定价下方）
- API：`/miniapp-admin/api/mall/*`，鉴权 cookie / `X-Miniapp-Admin-Token`
- Token：`SHUXIN_MINIAPP_ADMIN_TOKEN` 或回退 `SHUXIN_ADMIN_TOKEN`；**未配置则无法登录**（无硬编码默认值）
- 发货字段：`shipping_carrier` + `shipping_no`

## API 约定

- 认证：`session_token`（POST body）
- 商城前缀：`/api/mall/*`
- 充值前缀：`/api/payment/*`（不变）
- Admin 兼容：`/admin/api/mall/*`（`X-Admin-Token`）

## 嵌入方式

**V1（2026-07-20）**：TabBar **设备 | 商城 | 我的**；主包注册 `pages/mall/index`；个人中心「商城订单」可用。

## 烟测清单

1. `.env` 配置 `SHUXIN_ADMIN_TOKEN`，打开 `/miniapp-admin` 登录
2. 商城管理新建商品 + 多个 SKU → 上架
3. 小程序商城浏览 → 选规格加购 → 地址 → 下单支付（需微信支付；`SHUXIN_WECHAT_MOCK=1` 时下单会 503）
4. 待支付取消后库存回补；超时未付同样释放
5. 运营台对已支付订单填写快递公司 + 运单号 → 小程序订单列表可见

## PR 约束

- 单 PR 不跨 `device` + `mall` 目录
- 设备绑定流程不被商城 PR 修改
- 不做 Java 外挂整站商城
