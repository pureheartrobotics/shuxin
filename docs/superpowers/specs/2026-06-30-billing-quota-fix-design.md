# 充值额度更新问题及月度套餐限购设计规范

## 1. 背景与问题描述
在目前的陪伴型 AI 智能体框架中，微信小程序的充值和额度显示存在以下三个关键问题：
1. **充值后通话时长仍显示 0 分钟**：用户在微信小程序充值包月套餐或弹性加油包后，给钱了但分钟数额度并没有加上。原因是设备的跨月惰性重置机制在用户刷新或扣费时被错误触发（由于充值时未更新 `last_reset_month`），导致新充值的额度被强制清零覆盖。
2. **月度套餐可以重复购买**：用户购买了当前的包月套餐后，在其有效期内依然可以重复下单购买该套餐，导致套餐的到期时间被直接重置为 30 点（30 天），而非顺延累加，造成用户额度流失。
3. **无额度或无设备时显示破折号 `—`**：当用户未绑定设备或账户无额度时，界面上显示 `—`，容易引起歧义。这需要改回显示为 `0 分钟`。
4. **限购报错提示交互不佳**：用户在小程序选择购买已拥有的套餐时，若只在个人中心下方的消息提示区显示 `您已拥有该月度套餐，在有效期内无法重复购买`，文字不够醒目。应该改为使用模态弹窗（Modal）进行强提示。

---

## 2. 详细设计方案

### 2.1 充值成功同步校准当前月份 (解决充值被覆写为 0)
在 [postgres_repository.py](file:///home/peter/huada/project/Interesting/codex_agent/shuxin/src/shuxin/voice/postgres_repository.py) 的 `fulfill_payment_order` 方法中，当充值逻辑被触发并更新 `devices` 表时，同时获取当前服务器时间的月份并更新 `last_reset_month` 字段。
- **包月套餐充值 SQL 修改**：
  ```sql
  UPDATE devices
  SET subscription_plan_id = $2,
      subscription_minutes_limit = $3,
      subscription_minutes_used = 0.0000,
      subscription_expires_at = now() + INTERVAL '30 days',
      last_reset_month = $4,  -- 新增校准
      updated_at = now()
  WHERE device_id = $1
  ```
- **弹性加油包充值 SQL 修改**：
  ```sql
  UPDATE devices
  SET fuel_minutes_balance = COALESCE(fuel_minutes_balance, 0.0000) + $2,
      last_reset_month = $3,  -- 新增校准
      updated_at = now()
  WHERE device_id = $1
  ```

### 2.2 限制在有效期内重复购买同款月度套餐
在 [postgres_repository.py](file:///home/peter/huada/project/Interesting/codex_agent/shuxin/src/shuxin/voice/postgres_repository.py) 的 `create_payment_order` 方法中增加限制条件。如果用户已绑定设备且该设备的月度订阅套餐（`subscription_plan_id`）与当前请求的 `plan_id` 相同，且订阅尚未过期（`subscription_expires_at > now`），则直接拦截并抛出 `PermissionError`，禁止生成订单。

### 2.3 零额度/无设备状态友好展示为 0 分钟
在 [postgres_repository.py](file:///home/peter/huada/project/Interesting/codex_agent/shuxin/src/shuxin/voice/postgres_repository.py) 的 `get_device_quota` (当 `row is None` 时) 以及 `get_user_quota_by_user_id` (无活跃绑定设备时) 中，将返回的字典中的 `"configured": False` 修改为 `"configured": True`。

### 2.4 小程序重复购买套餐时弹窗提示
在小程序前端 [profile.vue](file:///home/peter/huada/project/Interesting/codex_agent/shuxin/apps/wechat-miniprogram/src/pages/profile/profile.vue) 的 `purchasePlan` 方法中，在 `catch` 块中捕获接口报错时：
- 对错误消息字符串进行检测。如果报错文本中包含关键字 `"无法重复购买"`，则调用 `uni.showModal` 弹出警告弹窗。
- 其他无关的报错，依然回退显示在个人中心页面下方的消息区。

---

## 3. 涉及修改的文件与代码范围

1. **[postgres_repository.py](file:///home/peter/huada/project/Interesting/codex_agent/shuxin/src/shuxin/voice/postgres_repository.py)**
   - `get_device_quota`: 修改未找到设备时的 fallback。
   - `get_user_quota_by_user_id`: 修改无活跃绑定设备时的 fallback。
   - `create_payment_order`: 增加订阅套餐的查重限购逻辑。
   - `fulfill_payment_order`: 在更新设备额度时同步写入 `last_reset_month`。

2. **[profile.vue](file:///home/peter/huada/project/Interesting/codex_agent/shuxin/apps/wechat-miniprogram/src/pages/profile/profile.vue)**
   - `purchasePlan`: 在 `catch` 中判断错误文本，引入 `uni.showModal` 弹窗。

---

## 4. 测试与验收标准
1. **单元测试验证**：
   - 编写 `tests/test_miniapp_billing.py` 中的限购测试用例，确保对同一个未过期的套餐调用 `create_payment_order` 时，系统抛出 `PermissionError`。
   - 编写充值测试用例，确保 `fulfill_payment_order` 在充值时成功向 `devices` 写入了当前月份的 `last_reset_month`。
2. **人工测试验收**：
   - 用户已拥有活跃月卡时，尝试再次点击购买同款套餐，应弹出弹窗提示：“您已拥有该月度套餐，在有效期内无法重复购买”。
   - 充值包月套餐或弹性加油包后，微信支付 notify 成功，刷新页面，额度能正常加上且不会变为 0。
   - 无设备或无额度时，个人中心页面正常展示 `0 分钟`，而不是 `—`。
