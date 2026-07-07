# 设计文档：小程序 BLE 配网修复

**日期**：2026-07-06
**作者**：Antigravity
**状态**：待实现
**相关文件**：
- `apps/wechat-miniprogram/src/pages/prov/ble.vue`
- `apps/wechat-miniprogram/src/pages/prov/esp-idf-prov/ble-transport.ts`

---

## 1. 背景

小程序已具备完整的 ESP-IDF BLE 配网协议栈（`esp-idf-prov/`），对齐量产固件 `shuxin_sep32` 的 `wifi_prov_scheme_ble` + `WIFI_PROV_SECURITY_1`（PoP = `shuxin`）。实测发现两个 bug 阻断配网流程，固件侧无需修改，仅修小程序。

---

## 2. 问题

### Bug 1：BLE 连接超时（主阻塞）

**现象**：扫描到 `SX-xxxxxx` 后点击连接，报 `createBLEConnection:fail connect timeout`，Android 必现，iOS 偶发。

**根因**：`connectDevice()` 中停止扫描（`finishScanning()`）和发起连接（`createBLEConnection`）几乎同时触发：

```ts
finishScanning();             // 内部 void stopBluetoothDiscovery()，不 await
uni.createBLEConnection(...)  // 立即发起，扫描可能仍在运行
```

Android BLE 栈在扫描未停止时发起连接会引发冲突，导致连接超时。

### Bug 2：`notifyBLECharacteristicValueChange:fail:nocharacteristic`（次阻塞）

**现象**：BLE 连接建立后，`establishSession()` 调用 `notifyBLECharacteristicValueChange` 时报 `nocharacteristic`。

**根因**：`discoverEndpoints()` 读取描述符失败时，fallback 用 `deriveEndpointCharacteristicUuid()` 推导的 UUID 字符串存入 `endpoints`。微信 BLE API 硬约束：`notifyBLECharacteristicValueChange` 的 `characteristicId` **必须是 `getBLEDeviceCharacteristics` 实际返回的原始字符串**，自行构造的字符串会报 `nocharacteristic`。

---

## 3. 设计

### 3.1 修 Bug 1：await 停止扫描再连接

**改动文件**：`ble.vue`

`connectDevice()` 改为 async，显式 await `stopBluetoothDiscovery()`，再等 200ms，再发起连接：

```ts
async function connectDevice(device: BleDeviceItem) {
  if (targetDeviceId.value) return;
  targetDeviceId.value = device.deviceId;
  errorMsg.value = "";

  // 1. await 停止扫描（不再 void）
  clearScanTimeout();
  await stopBluetoothDiscovery();
  markBluetoothDiscoveryStopped();
  isScanning.value = false;

  // 2. 给 Android BLE 栈 200ms 喘息
  await new Promise<void>((r) => setTimeout(r, 200));

  // 3. 发起连接（下方逻辑不变）
  addLog(`尝试建立蓝牙连接: ${device.name}`);
  uni.createBLEConnection({ ... });
}
```

`finishScanning()` 函数本身**不修改**，其他调用点保持原有行为。

### 3.2 修 Bug 2：fallback 用微信原始 UUID

**改动文件**：`ble-transport.ts`，`discoverEndpoints()` 方法

遍历特征值时建立 **「推导 UUID → 微信原始 UUID」** 映射表，fallback 阶段从此表取值：

```ts
// 遍历特征值时建立映射
const wechatUuidMap: Record<string, string> = {};
for (const characteristic of characteristics.characteristics || []) {
  for (const shortUuid of Object.values(DEFAULT_ENDPOINT_SHORT_UUID)) {
    const derived = deriveEndpointCharacteristicUuid(this.serviceUuid, shortUuid);
    if (bluetoothUuidMatches(characteristic.uuid, derived)) {
      wechatUuidMap[derived.toLowerCase()] = characteristic.uuid;
    }
  }
}

// fallback：从映射表取原始 UUID，取不到才用推导值（兜底）
for (const [name, shortUuid] of Object.entries(DEFAULT_ENDPOINT_SHORT_UUID)) {
  if (!this.endpoints[name]) {
    const derived = deriveEndpointCharacteristicUuid(this.serviceUuid, shortUuid);
    this.endpoints[name] = wechatUuidMap[derived.toLowerCase()] ?? derived;
  }
}
```

同时删除调试临时加入的两条 `console.log`。

---

## 4. 改动范围

| 文件 | 改动性质 | 行数估算 |
|------|---------|---------|
| `ble.vue` | `connectDevice` 改 async，加 await + 200ms | +6 / -3 |
| `ble-transport.ts` | fallback 改用原始 UUID + 删调试 log | +12 / -8 |

**不改动**：`security1.ts`、`provision-client.ts`、`bluetooth-uuid.ts`、`constants.ts`、固件

---

## 5. 边界与约束

- `stopBluetoothDiscovery` 已是 Promise，直接 await 即可
- `connectDevice` 改 async 后模板 `@tap="connectDevice(device)"` 调用不受影响
- 200ms 延迟用户无感知
- `wechatUuidMap` 匹配失败时保留 `?? derived` 兜底，不会 throw
- fallback UUID 映射表只在 `discoverEndpoints()` 作用域内使用，无副作用

---

## 6. 验收标准

1. Android 真机：扫描 SX 设备 → 点连接 → 不再出现 `createBLEConnection:fail connect timeout`
2. Security1 握手日志出现「安全会话建立成功」
3. 填写正确 Wi-Fi 密码 → 状态轮询最终出现「设备联网成功」
4. 填写错误密码 → 出现「Wi-Fi 密码错误」提示
5. iOS 真机同等验收

---

## 7. 后续

- 调试 `console.log` 随本次修复一并删除
- 如固件后续将 PoP 从固定 `shuxin` 改为 `device_code`，需同步修改 `constants.ts` 中 `PROVISION_POP` 的取值逻辑（见 `WECHAT_BLE_PROVISIONING_HANDOFF.md` §3.2）
