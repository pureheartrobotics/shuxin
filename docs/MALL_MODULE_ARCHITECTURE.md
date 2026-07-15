# 微信小程序商城模块架构

## 模块边界

初心小程序 = **一个 App、三个业务模块**，共享登录与 HTTP 基建：

| 模块 | 目录 | 职责 |
|------|------|------|
| Device | `modules/device/` | 设备绑定、BLE 配网、工厂 QA |
| Mall | `modules/mall/` | 实体商品浏览、购物车、下单 |
| Account | `modules/account/` | 登录态、个人中心、**时长充值（保持 profile 弹窗）** |

横切：`core/http.ts`、`core/auth.ts`

## 前端分层

```
Page → composables → modules/*/api → core/http → 后端 API
```

禁止：页面内联 `uni.request`、单文件 500+ 行业务逻辑。

## 后端分层

```
Router → Service → Repository → Postgres
         ↘ Gateway (微信支付)
```

| 层 | 路径 | 职责 |
|----|------|------|
| Router | `api/routers/mall/`、`api/routers/payment/` | 参数校验、HTTP 响应 |
| Service | `services/mall/`、`services/payment/` | 业务编排 |
| Repository | `persistence/mall_repo.py` | CRUD |
| Gateway | `services/payment/wechat_pay_gateway.py` | 微信 SDK 封装 |

## 支付分离

- **QuotaPaymentService**：时长充值，`payment_orders` 表，profile 弹窗流程不变
- **MallPaymentService**：实体商品，`mall_orders` 表，`out_trade_no` 前缀 `mx`
- 共用 `WeChatPayGateway`；notify 按 `out_trade_no` 前缀路由

## API 约定

- 认证：`session_token`（POST body 或 query）
- 商城前缀：`/api/mall/*`
- 充值前缀：`/api/payment/*`（不变）
- Admin 商城：`/admin/api/mall/*`

## 嵌入方式

**量产现状（2026-07-13）**：TabBar 仅 **设备 | 我的**；主包未注册 `pages/mall/index`；个人中心「商城订单」已注释。`modules/mall/` 分包与后端 `/api/mall/*` **保留**，恢复时加回主包页 + Tab 第三项 + 取消 profile 注释即可。

历史嵌入方式（恢复时）：TabBar **设备 | 商城 | 我的**；商城页面放 `subPackages`（`modules/mall`）。

## PR 约束

- 单 PR 不跨 `device` + `mall` 目录
- 设备绑定流程不被商城 PR 修改
