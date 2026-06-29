# 硬件设备额度耗尽提示与本地播报对接规格文档

本文档定义了当用户使用时长（包月订阅分钟数、加油包分钟数以及每日低保）全部用完时，服务器与硬件设备（下称固件）之间的 WebSocket 交互协议规范，以及如何在开发调试中快速模拟并测试该场景。

---

## 1. 业务逻辑与阻断策略

当设备发起语音交互（`listen` 事件或音频 data 上行）时，服务端会对绑定该设备的用户进行分钟额度可用性校验：
1. **优先扣减**：按月订阅分钟限制内已用分钟数。
2. **次要扣减**：若订阅已满，扣减弹性加油包余额。
3. **低保兜底**：若上述二者皆为 0，且系统启用了“每日低保”功能，则使用今日未超限的每日免费低保（默认每天 1.5 分钟）。
4. **完全耗尽**：若以上三部分均扣减完毕，服务端判定该用户额度完全用尽，直接阻断本轮会话，不触发 LLM 推理与 TTS 语音合成，立即向 WebSocket 下发错误标识。

---

## 2. WebSocket 下行协议规范

当判定额度耗尽时，服务端发送单条控制帧以结束本次对话。

### 协议格式 (JSON)

```json
{
  "type": "error",
  "error_kind": "quota_exhausted",
  "message": "额度已用尽，请充值"
}
```

* **`type`**: 固定字符串 `"error"`，标识本帧为发生异常导致的阻断。
* **`error_kind`**: 错误子分类，固定字符串 `"quota_exhausted"`，供固件识别该特定业务场景。
* **`message`**: 用户友好文字说明（如需要屏幕显示）。

### 固件处理行为规范

固件在接收到上述帧后，应执行以下操作：
1. **停止录音与发送**：关闭本地音频上行通路（如有积压 PCM 帧，立即丢弃）。
2. **停止播放**：打断当前可能正在播放的任何合成流或提示音。
3. **本地语音播报**：检索固件本地存储器（如 Flash）中的特定配音文件（如 `recharge_prompt.wav`），内容提示：“您的通话余额已用尽，请进入小程序充值续费。”并进行外放播报。

---

## 3. 开发测试与模拟方法

为了避免实际通话 120 分钟进行测试，研发与测试人员可以通过直连数据库修改设备额度，实现秒级复现。

### 步骤 1：查询您的设备 ID
在服务控制台对应的 Docker 容器中执行查询：
```bash
docker exec shuxin-postgres psql -U shuxin -d shuxin -c "SELECT device_id, subscription_minutes_limit, subscription_minutes_used FROM devices;"
```
从列表中找到您当前调试设备的 ID（通常以 `SX-` 或特定 uuid 字符串开头）。

### 步骤 2：直接模拟扣光订阅分钟数和每日低保
在终端中执行以下 SQL 更新命令（将 `YOUR_DEVICE_ID` 替换为上一步查询到的 ID）：
```bash
docker exec shuxin-postgres psql -U shuxin -d shuxin -c "UPDATE devices SET subscription_minutes_used = 120.0, daily_allowance_date = CURRENT_DATE, daily_allowance_seconds_used = 90.0 WHERE device_id = 'YOUR_DEVICE_ID';"
```
*(注：`120.0` 为该套餐包月上限，`90.0` 秒即低保的 1.5 分钟上限)*

### 步骤 3：发起语音测试并验证
1. 打开网页端调试页面或小程序，检查个人中心/绑定设备的显示时长是否成功归零（`0 分钟`）。
2. 按压设备或触发对话，观察 WebSocket 调试日志：
   * 验证是否在 `stt/start` 之后立即收到了 `{"type":"error","error_kind":"quota_exhausted","message":"额度已用尽，请充值"}` 的下行帧。
   * 验证固件此时是否成功打断了正常流程并触发本地警报音频播报。
