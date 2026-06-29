# 设备独立计费额度重构、提示词修改与本地音频生成规格文档

本文档定义了如何将原先绑定在“用户 (User)”上的分钟额度体系重构解耦为绑定在“设备 (Device)”上、修改限额提示词文案为“请充值”，以及利用内置工具链为固件端生成对应的 `.ogg` 和 `.opus.bin` 本地语音资产文件的具体方案。

---

## 1. 核心设计原则

1. **设备级独立流量计费 (Device-level Billing)**
   为了支持同一个用户绑定多台设备时的独立计费需求，所有额度参数（订阅套餐、加油包、每日低保已用时间）均从 `users` 表剥离，变更为 `devices` 表的属性。扣除时长和查询剩余分钟数均以 `device_id` 为唯一锚点。
2. **本地自愈友好文案**
   将错误帧文案统一调整为 `"额度已用尽，请充值"`。同时将其加入硬件提示音索引，利用服务端工具链统一生成脱机 Opus 语音，供固件开发同事在本地 Flash 中烧录。

---

## 2. 详细设计与改动范围

### 2.1 数据库结构迁移 (`014_move_quota_to_devices.sql`)

* **涉及文件**: [014_move_quota_to_devices.sql](file:///home/peter/huada/project/Interesting/codex_agent/shuxin/src/shuxin/voice/migrations/014_move_quota_to_devices.sql)
* **SQL 脚本**:
  ```sql
  -- 从 users 表移除额度字段（如果为了完全兼容保留，我们可以仅作废或转移，这里直接新增到 devices 中）
  ALTER TABLE devices
      ADD COLUMN IF NOT EXISTS subscription_plan_id text REFERENCES miniapp_subscription_plans(plan_id) ON DELETE SET NULL,
      ADD COLUMN IF NOT EXISTS subscription_minutes_limit integer NOT NULL DEFAULT 0,
      ADD COLUMN IF NOT EXISTS subscription_minutes_used numeric(12, 4) NOT NULL DEFAULT 0.0000,
      ADD COLUMN IF NOT EXISTS subscription_expires_at timestamptz,
      ADD COLUMN IF NOT EXISTS fuel_minutes_balance numeric(12, 4) NOT NULL DEFAULT 0.0000,
      ADD COLUMN IF NOT EXISTS last_reset_month varchar(7) NOT NULL DEFAULT '',
      ADD COLUMN IF NOT EXISTS daily_allowance_date date,
      ADD COLUMN IF NOT EXISTS daily_allowance_seconds_used numeric(8, 2) NOT NULL DEFAULT 0.00;
  ```

### 2.2 仓储层重构 (`postgres_repository.py`)

* **涉及文件**: [postgres_repository.py](file:///home/peter/huada/project/Interesting/codex_agent/shuxin/src/shuxin/voice/postgres_repository.py)
* **改动点**:
  * 编写 `get_device_quota(self, device_id: str) -> dict[str, Any]` 方法：
    * 从 `devices` 表查询上述额度状态。
    * 处理跨月重置逻辑（如果是新月份，将 `subscription_minutes_used` 与 `fuel_minutes_balance` 归零，并更新 `last_reset_month`）。
  * 重构 `get_user_quota_by_user_id(self, user_id: str)`：
    * 查询该用户当前绑定的**首台活跃设备**，并返回该设备的 quota 属性以维持小程序端兼容显示。
  * 重构 `deduct_user_minutes_quota(self, user_id: str, cost_minutes: float)` 为 `deduct_device_minutes_quota(self, device_id: str, cost_minutes: float)`：
    * 依据 `devices.device_id` 对该设备执行扣减。
  * 重构首次激活赠送逻辑：
    * 当在 `_bind_device_for_user` 中判定为首次激活时，直接在 `devices` 表中更新该设备的套餐和时间限制。

### 2.3 调用链路与服务层适配 (`billing.py` / `server.py`)

* **涉及文件**: 
  * [billing.py](file:///home/peter/huada/project/Interesting/codex_agent/shuxin/src/shuxin/voice/billing.py)
  * [server.py](file:///home/peter/huada/project/Interesting/codex_agent/shuxin/src/shuxin/voice/server.py)
* **改动点**:
  * `BillingService.record_usage_in_background` 入参增加 `device_id: str`，异步扣费时调用 `deduct_device_minutes_quota`。
  * WebSocket 服务处理：
    * 一轮对话结束时，将 `device_id` 传递给计费服务。
    * 对话开始前，在 `_ensure_runtime` 中使用 `self.repo.assert_device_quota_available(self.device_id)` 校验设备额度（若已用尽，同样返回带 `error_kind: "quota_exhausted"` 的错误帧）。
  * 支付与订单处理：
    * 微信充值下单 `/api/payment/create-order` 入参增加（或从当前绑定关系中获取）`device_id`，订单履约回调时直接增加对应 `devices` 的额度。

### 2.4 文案替换与本地提示音自动生成

* **涉及文件**:
  * [dmx_client.py](file:///home/peter/huada/project/Interesting/codex_agent/shuxin/src/shuxin/voice/dmx_client.py) (常量 `QUOTA_EXHAUSTED_MESSAGE` 改为 `"额度已用尽，请充值"`)
  * [strings.zh-CN.json](file:///home/peter/huada/project/Interesting/codex_agent/shuxin/data/device_assets/strings.zh-CN.json) (增加键 `"QUOTA_EXHAUSTED": "额度已用尽，请充值"`)
* **运行音频生成工具**:
  * 运行 `python scripts/generate_device_prompt_assets.py --keys QUOTA_EXHAUSTED`，调用系统内置 TTS（如火山引擎）合成此句提示音，并在 `data/device_assets/zh-CN/` 下输出：
    * `quota_exhausted.ogg` (Opus-in-Ogg 格式)
    * `quota_exhausted.opus.bin` (裸 Opus 帧格式)

---

## 3. 验证计划

1. **多设备独立扣减测试**：
   * 在同一个用户下绑定两台设备 `device_A` 和 `device_B`。
   * 分别向两台设备发起语音通话，验证扣费分别记在各自设备的数据库记录中，互不干扰。
2. **提示音资产验证**：
   * 确认 `data/device_assets/zh-CN/` 下生成的 `quota_exhausted.ogg` 和 `quota_exhausted.opus.bin` 音频文件存在，且发音内容为“额度已用尽，请充值”。
