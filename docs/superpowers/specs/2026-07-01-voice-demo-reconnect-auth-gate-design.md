# 语音测试台自动重连与连接鉴权门禁设计说明书

## 1. 概述与现状分析

在目前的语音测试台 (`http://localhost:8765/voice-demo`) 中，存在以下两个问题：
1. **下拉菜单切换与连接状态不一致**：当用户切换测试的目标设备/用户下拉框时，已建立的 WebSocket 连接并不会自动关闭并重新对新设备建连。由于输入框数值被修改，用户直观感觉连接已经变更，但实际上后台仍然对旧设备（默认为配置为空的 `demo-user`）运行。
2. **后端隐式未授权兜底**：当未鉴权（未成功处理 `hello` 握手）的 WebSocket 收到录音或文本对话消息时，后端会懒加载并将该连接兜底视为 `demo-user` 和 `demo-device-001` 的会话。这会导致误导性的报错 `LLM api_key is not configured for this device/user`，而不是明确告知连接鉴权失败。

本设计旨在通过前端自动重新建连和后端增加鉴权门禁拦截来彻底解决上述问题。

## 2. 详细设计方案

### 2.1 前端：下拉框切换自动重连 (Web UI)
修改 `src/shuxin/voice/server.py` 内的 `_web_demo_html` 前端 Javascript 代码。在 `testTargetSelect.onchange` 触发时，检查当前的 `ws` 状态：
- 若 WebSocket 处于 `OPEN` 或 `CONNECTING` 状态，输出提示日志，主动关闭当前 WebSocket 并等待 150ms 触发 `connectBtn.click()` 进行全新连接。

```javascript
    testTargetSelect.onchange = () => {
      const item = demoTargets[Number(testTargetSelect.value)];
      if (!item) {
        llmPreviewEl.textContent = '-';
        applyLlmPreviewStyle(null);
        return;
      }
      deviceInput.value = item.device_code || item.device_id;
      secretInput.value = item.device_secret || '';
      llmPreviewEl.textContent = renderLlmPreview(item);
      applyLlmPreviewStyle(item);
      log(`已选择 ${item.user_id} -> ${item.device_id} · Agent=${item.agent_display_name || item.agent_id || 'shuxin'}`);
      if (!item.llm_api_key_configured) {
        log('绑定用户未配置 API Key，请先在 /admin 用户页点击「配置 LLM」后再对话');
      }
      
      // 自动重新连接以更新 WebSocket 会话状态
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        log('正在切换目标设备，自动重新连接中...');
        ws.close();
        setTimeout(() => {
          connectBtn.click();
        }, 150);
      }
    };
```

### 2.2 后端：鉴权门禁拦截 (Backend Security Gate)
修改 `src/shuxin/voice/server.py` 的 WebSocket `_handle_text` 消息处理器：
- 在接收到任何 `listen` (启动录音说话) 或 `text_turn` (文本消息发起) 事件时，检查当前会话的 `self.user_settings` 是否为 `None`（这意味着 `hello` 消息未接收，或接收了但校验没通过）。
- 如果为 `None`，拒绝该事件的执行，并向前端返回 `{"type": "error", "message": "WebSocket session is not authenticated. Please select target and connect first."}`。

```python
        # 拦截未经过成功 hello 鉴权就直接发起对话的连接
        if message_type in {"listen", "text_turn"} and not self.user_settings:
            await self._send_json(
                {
                    "type": "error",
                    "message": "WebSocket session is not authenticated. Please select target and connect first.",
                }
            )
            return
```

## 3. 测试与验证计划

1. **单元测试验证**：
   - 编写针对 `_VoiceWebSocketSession._handle_text` 的测试用例，覆盖没有先发送 `hello` 但直接发送 `listen` 或 `text_turn` 的场景，确保能被拒绝并返回正确的错误事件。
2. **人工联调验证**：
   - 使用 `scripts/redeploy_docker.sh` 重新部署容器，访问 `http://localhost:8765/voice-demo`。
   - 尝试直接点击“按住说话”，校验是否弹回未鉴权错误。
   - 连接默认设备后切换下拉菜单到另一个设备，验证控制台是否输出“正在切换目标设备，自动重新连接中...”，并验证重新连接后能正确与对应的设备建立对话。
