# 设备独立计费与订阅时间跨度日常测试规格手册

本文档为开发与测试人员提供了一套**无需真实等待时间跨度**（如跨月、跨天、到期）即可模拟并验证设备分钟计费、限额、清零与微信充值回调的完整日常手动测试方案。

---

## 1. 测试前置准备

在进行所有场景的测试前，首先需要获取您当前测试设备的 `device_id`。

### 查询当前绑定的设备 ID
进入服务对应的 Postgres 容器中执行查询：
```bash
docker exec -it shuxin-postgres psql -U shuxin -d shuxin -c "SELECT device_id, name, subscription_minutes_limit, subscription_expires_at FROM devices;"
```
从列表中找到您当前登录/测试的设备 ID（例如 `SX-000119`）。

---

## 2. 核心测试用例与 SQL 模拟指令

### 场景 1：跨月订阅分钟数惰性清零测试 (Monthly Reset Simulation)

* **业务原理**：当新的自然月到来时，设备在上月消耗的包月订阅分钟数应自动清零。
* **模拟步骤**：
  1. 将设备的上次重置月份修改为过去的某个月（例如 `2026-05`），并人为设置已用分钟数：
     ```bash
     docker exec -it shuxin-postgres psql -U shuxin -d shuxin -c "UPDATE devices SET last_reset_month = '2026-05', subscription_minutes_used = 100.0000, fuel_minutes_balance = 5.0000 WHERE device_id = 'YOUR_DEVICE_ID';"
     ```
  2. 打开测试网页端或小程序，并触发一次按住说话语音交互。
* **预期验证结果**：
  * 对话正常进行（不被阻断）。
  * 重新查询数据库，发现设备的 `subscription_minutes_used` 自动归零（`0.0000`），`fuel_minutes_balance` 自动归零，且 `last_reset_month` 自动更新为当前真实的年份月份（例如 `2026-06`）。

---

### 场景 2：每日免费低保刷新测试 (Daily Allowance Reset Simulation)

* **业务原理**：若设备没有包月和加油包额度，系统每天会提供 1.5 分钟（90秒）的免费低保额度。过了午夜 12 点后，该低保额度应自动刷新。
* **模拟步骤**：
  1. 人为将设备的今日低保日期设置为昨天，且将已消耗的低保秒数设满（`90.00` 秒）：
     ```bash
     docker exec -it shuxin-postgres psql -U shuxin -d shuxin -c "UPDATE devices SET daily_allowance_date = CURRENT_DATE - 1, daily_allowance_seconds_used = 90.00 WHERE device_id = 'YOUR_DEVICE_ID';"
     ```
  2. 触发一次按住说话语音交互。
* **预期验证结果**：
  * 对话正常进行。
  * 重新查询数据库，发现设备的 `daily_allowance_seconds_used` 自动重置为 `0.00`，且 `daily_allowance_date` 被更新为今日日期，证明低保在当日首次交互时自愈刷新。

---

### 场景 3：额度完全到期/耗尽阻断测试 (Subscription Expiry & Exhaustion)

* **业务原理**：当设备订阅过期、加油包为 0 且今日低保已耗尽时，系统必须立即打断会话，下发 `quota_exhausted` 错误码，固件应触发本地“请充值”配音。
* **模拟步骤**：
  1. 扣光设备的所有可用时间，并将订阅到期时间设置为过去：
     ```bash
     docker exec -it shuxin-postgres psql -U shuxin -d shuxin -c "UPDATE devices SET subscription_expires_at = now() - interval '1 day', fuel_minutes_balance = 0.0000, daily_allowance_date = CURRENT_DATE, daily_allowance_seconds_used = 90.00 WHERE device_id = 'YOUR_DEVICE_ID';"
     ```
  2. 触发一次按住说话语音交互。
* **预期验证结果**：
  * 网页端/固件立即收到下行的阻断消息：
    ```json
    {
      "type": "error",
      "error_kind": "quota_exhausted",
      "message": "额度已用尽，请充值"
    }
    ```
  * 固件端或网页端成功停止录音，并播报本地的“额度已用尽，请充值”语音。

---

### 场景 4：微信支付履约模拟充值测试 (Fulfillment Simulation)

* **业务原理**：用户付费成功后，微信支付后台会发送异步回调，系统接收后立即为特定设备充值增加分钟数或加油包。
* **模拟步骤**：
  1. 使用小程序或接口创建充值订单，拿到商户订单号 `out_trade_no`。
  2. 在本地非生产调试状态下，可通过数据库直接将订单状态更改为已支付（模拟回调到账）：
     ```bash
     docker exec -it shuxin-postgres psql -U shuxin -d shuxin -c "UPDATE payment_orders SET status = 'paid' WHERE out_trade_no = 'sx_YOUR_OUT_TRADE_NO';"
     ```
  3. 或者直接模拟支付平台回调接口请求：
     ```bash
     curl -X POST http://localhost:8765/api/payment/notify \
       -H "Content-Type: application/json" \
       -d '{"out_trade_no": "sx_YOUR_OUT_TRADE_NO", "result_code": "SUCCESS"}'
     ```
     *(注：非 Mock 状态下可能需要微信支付签名，在开发阶段可通过 `SHUXIN_WECHAT_MOCK=1` 进行本地 Mock 支付测试)*
* **预期验证结果**：
  * 订单状态变更，设备对应的时长增加（订阅时间延长或加油包额度上涨）。
