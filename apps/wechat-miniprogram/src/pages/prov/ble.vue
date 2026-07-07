<template>
  <view class="page">
    <view v-if="showPrivacyGate" class="privacy-overlay" @tap.stop>
      <view class="privacy-card" @tap.stop>
        <view class="privacy-title">隐私保护提示</view>
        <view class="privacy-desc">
          蓝牙配网需要使用蓝牙连接设备，并可能读取附近 Wi-Fi 列表。请阅读并同意
          <text class="privacy-link" @tap="onOpenPrivacyContract">{{ privacyContractName }}</text>
          后继续。
        </view>
        <view class="privacy-hint">若随后出现微信系统弹窗，请先勾选隐私协议再点「允许」。</view>
        <view class="privacy-actions">
          <button class="ghost" @tap="onPrivacyDisagree">暂不同意</button>
          <button
            id="ble-privacy-agree-btn"
            class="primary"
            open-type="agreePrivacyAuthorization"
            @agreeprivacyauthorization="onPrivacyAgreed"
          >
            同意并继续
          </button>
        </view>
      </view>
    </view>

    <!-- 头部说明 -->
    <view class="hero">
      <view class="eyebrow">CHUXIN PROVISIONING</view>
      <view class="title">设备蓝牙配网</view>
      <view class="subtitle">通过手机蓝牙，将 Wi-Fi 账号和密码发送给初心设备，帮助设备连接网络。</view>
    </view>

    <!-- 步骤指示器 -->
    <view class="steps-indicator">
      <view class="step-node" :class="{ active: currentStep >= 1, completed: currentStep > 1 }">
        <view class="step-num">1</view>
        <text class="step-text">寻找设备</text>
      </view>
      <view class="step-line" :class="{ active: currentStep > 1 }"></view>
      <view class="step-node" :class="{ active: currentStep >= 2, completed: currentStep > 2 }">
        <view class="step-num">2</view>
        <text class="step-text">配置 Wi-Fi</text>
      </view>
      <view class="step-line" :class="{ active: currentStep > 2 }"></view>
      <view class="step-node" :class="{ active: currentStep >= 3, completed: currentStep > 3 }">
        <view class="step-num">3</view>
        <text class="step-text">连接状态</text>
      </view>
    </view>

    <!-- 第一步：搜索并连接设备 -->
    <view v-if="currentStep === 1" class="panel">
      <view class="panel-header">
        <view class="panel-title">第一步：搜索设备</view>
        <view class="panel-desc">{{ scanPanelDesc }}</view>
      </view>

      <view class="scan-container">
        <!-- 扫描中状态 -->
        <view v-if="isScanning" class="scan-active">
          <view class="radar-box">
            <view class="radar-circle c1"></view>
            <view class="radar-circle c2"></view>
            <view class="radar-circle c3"></view>
            <view class="breathing-glow-inner">
              <text class="radar-search-icon">🔍</text>
            </view>
            <text class="radar-status">{{ scanActiveHint }}</text>
          </view>
          <text class="scan-summary">已发现 {{ discoveredDevices.length }} 台设备</text>
          <button class="ghost stop-scan" @tap.stop="stopScan">停止搜索</button>
        </view>

        <!-- 未扫描状态（拟物盘片风格） -->
        <view v-else class="scan-idle" @tap="startScan">
          <view class="radar-box idle">
            <!-- 虚线环圈轨道 -->
            <view class="radar-orbit o1"></view>
            <view class="radar-orbit o2"></view>
            <!-- 绿色实体大盘片 -->
            <view class="scan-plate-btn">
              <text class="plate-icon">📡</text>
              <text class="plate-text">开始搜索</text>
            </view>
          </view>
          <text class="scan-hint">{{ scanIdleHint }}</text>
        </view>

        <!-- 蓝牙列表 (优化卡片式结构) -->
        <scroll-view scroll-y class="device-list">
          <view v-if="discoveredDevices.length === 0" class="empty-list">
            {{ isScanning ? scanEmptyListHint : '点击上方按钮开始搜索' }}
          </view>
          <view
            v-for="device in discoveredDevices"
            :key="device.deviceId"
            class="device-item"
            :class="{ connecting: targetDeviceId === device.deviceId }"
            @tap="connectDevice(device)"
          >
            <view class="device-info">
              <view class="device-name-row">
                <text class="device-name">{{ device.name }}</text>
                <text v-if="device.rawName.toLowerCase().startsWith('sx')" class="device-tag my-chuxin">我的初心</text>
                <text v-else-if="!device.rawName" class="device-tag test-device">测试机</text>
              </view>
              <view class="device-rssi-row">
                <text class="device-signal-bar" :style="{ color: getSignalColor(device.RSSI) }">📶 {{ getSignalText(device.RSSI) }}</text>
                <text class="device-rssi-value">({{ device.RSSI }} dBm)</text>
              </view>
            </view>
            <view class="device-action">
              <text v-if="targetDeviceId === device.deviceId" class="action-text connecting">连接中...</text>
              <text v-else class="action-text">点击连接 ➔</text>
            </view>
          </view>
        </scroll-view>
      </view>

      <view v-if="errorMsg" class="message error">{{ errorMsg }}</view>

      <!-- 折叠调试日志 -->
      <view class="dev-log-section">
        <view class="dev-log-header" @tap="showConsoleLogs = !showConsoleLogs">
          <text class="dev-log-title">🛠️ 开发者调试日志</text>
          <text class="dev-log-arrow">{{ showConsoleLogs ? '收起 ▴' : '展开 ▾' }}</text>
        </view>
        <view v-if="showConsoleLogs && debugErr" class="message debug">{{ debugErr }}</view>
      </view>
    </view>

    <!-- 第二步：填写 Wi-Fi 信息 -->
    <view v-if="currentStep === 2" class="panel">
      <view class="panel-header">
        <view class="panel-title">第二步：配置 Wi-Fi</view>
        <view class="panel-desc">设备：<text class="connected-highlight">{{ connectedDeviceName }}</text> 已连接。请输入设备将要连接的无线网络信息。</view>
      </view>

      <view class="form-group">
        <view class="label">Wi-Fi 名称 (SSID)</view>
        <view class="wifi-input-row">
          <input class="input" v-model="wifiSsid" placeholder="请输入或选择 Wi-Fi 名称" />
          <button class="mini get-wifi" @tap="scanLocalWifi">扫描附近</button>
        </view>

        <view class="label" style="margin-top: 30rpx;">Wi-Fi 密码</view>
        <view class="password-input-row">
          <input
            class="input"
            :type="showPassword ? 'text' : 'password'"
            v-model="wifiPassword"
            placeholder="请输入 Wi-Fi 密码"
          />
          <view class="eye-icon" @tap="togglePasswordVisible">
            {{ showPassword ? '👁️' : '🔒' }}
          </view>
        </view>
      </view>

      <view class="actions">
        <button class="ghost" @tap="backToStep1">重新搜索</button>
        <button class="primary" :disabled="!wifiSsid || sendingConfig" @tap="sendWifiCredentials">
          {{ sendingConfig ? '正在发送...' : '发送配置 ➔' }}
        </button>
      </view>

      <view v-if="errorMsg" class="message error">{{ errorMsg }}</view>
    </view>

    <!-- 第三步：查看配网连接状态 -->
    <view v-if="currentStep === 3" class="panel">
      <view class="panel-header">
        <view class="panel-title">第三步：网络配置状态</view>
        <view class="panel-desc">正在将网络凭证发送给设备，并等待设备联网结果。</view>
      </view>

      <!-- 折叠调试日志 -->
      <view class="dev-log-section" style="margin-bottom: 20rpx;">
        <view class="dev-log-header" @tap="showConsoleLogs = !showConsoleLogs">
          <text class="dev-log-title">🛠️ 开发者调试日志</text>
          <text class="dev-log-arrow">{{ showConsoleLogs ? '收起 ▴' : '展开 ▾' }}</text>
        </view>
        <view v-if="showConsoleLogs" class="console-box">
          <view class="console-title">连接状态追踪</view>
          <scroll-view scroll-y class="console-log">
            <view v-for="(log, index) in logs" :key="index" class="log-line" :class="log.type">
              <text class="log-time">[{{ log.time }}]</text>
              <text class="log-text">{{ log.text }}</text>
            </view>
          </scroll-view>
        </view>
      </view>

      <!-- 成功/失败状态面板 -->
      <view v-if="provStatus === 'success'" class="status-panel success">
        <view class="status-icon">✓</view>
        <view class="status-title">配网成功</view>
        <view class="status-desc">设备已成功连接至 Wi-Fi 并获取 IP 地址。正在返回设备绑定页...</view>
      </view>

      <view v-if="provStatus === 'fail'" class="status-panel fail">
        <view class="status-icon">✕</view>
        <view class="status-title">配网失败</view>
        <view class="status-desc">{{ failureReason || '设备连接 Wi-Fi 失败，请检查密码或信号强度。' }}</view>
        <button class="primary retry-btn" @tap="retryProvisioning">重新配网</button>
      </view>

      <view v-if="provStatus === 'pending'" class="status-panel pending">
        <view class="spinner"></view>
        <view class="status-title" style="color: #6f665b;">正在联网中</view>
        <view class="status-desc">请保持手机靠近设备，等待设备连接到路由器...</view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { onHide, onUnload } from "@dcloudio/uni-app";
import { onMounted, onUnmounted, ref } from "vue";
import {
  closeBleAdapter,
  ensureBleReady,
  getBleDebugDetail,
  mapBleError,
  markBluetoothDiscoveryStopped,
  shouldShowPrivacyGateForBleError,
  startBluetoothDiscovery,
  stopBluetoothDiscovery,
} from "../../utils/ble-permissions";
import {
  BLE_FILTER_SX_PREFIX_ONLY,
  BLE_SCAN_DURATION_MS,
  extractDeviceCodeFromBleName,
  getBleAdvertisedName,
  getBleDeviceListName,
  shouldIncludeBleDevice,
  sortDiscoveredDevices,
} from "../../utils/ble-discovery";
import {
  EspIdfProvisionClient,
  mapWifiStatusToMessage,
  type WifiProvisionStatus,
} from "./esp-idf-prov";
import { PROVISION_POP } from "./esp-idf-prov/constants";
import {
  checkBlePrivacyNeeded,
  mapPrivacyError,
  loadPrivacyContractName,
  notifyPrivacyAgreed,
  notifyPrivacyDenied,
  openPrivacyContract,
  PRIVACY_AGREE_BUTTON_ID,
  PrivacyBackendError,
  PrivacyDeniedError,
  PrivacyNeedAgreeError,
  setPrivacyGateHandler,
} from "../../utils/privacy";

type BleDeviceItem = {
  deviceId: string;
  name: string;
  rawName: string;
  RSSI: number;
};

const scanPanelDesc = BLE_FILTER_SX_PREFIX_ONLY
  ? "请先打开手机蓝牙。确认设备指示灯正在快闪（表示等待连接），点击下方「开始搜索」，在列表中选择你的初心设备并点击连接。"
  : "【调试模式】会显示附近所有蓝牙设备，方便技术人员排查问题。请选择目标设备后点击连接。";

const scanActiveHint = BLE_FILTER_SX_PREFIX_ONLY ? "正在搜索附近的初心设备..." : "正在搜索附近蓝牙设备...";

const scanIdleHint = BLE_FILTER_SX_PREFIX_ONLY
  ? "点击开始搜索附近的初心设备"
  : "点击开始搜索附近所有蓝牙设备（调试模式）";

const scanEmptyListHint = BLE_FILTER_SX_PREFIX_ONLY
  ? "还没有找到初心设备，请确认设备指示灯正在快闪"
  : "还没有找到蓝牙设备，请确认手机蓝牙已打开";

const scanNoDeviceError = BLE_FILTER_SX_PREFIX_ONLY
  ? "没有找到初心设备，请确认设备指示灯正在快闪"
  : "没有找到蓝牙设备，请确认手机蓝牙已打开";

const scanNoDeviceTimeoutError = BLE_FILTER_SX_PREFIX_ONLY
  ? "搜索超时，没有找到初心设备。请确认设备指示灯正在快闪后重试"
  : "搜索超时，没有找到蓝牙设备。请确认手机蓝牙已打开后重试";

const scanFoundDebugLabel = BLE_FILTER_SX_PREFIX_ONLY ? "台初心设备" : "台蓝牙设备（调试）";

// 状态管理
const currentStep = ref(1);
const isScanning = ref(false);
const discoveredDevices = ref<BleDeviceItem[]>([]);
const errorMsg = ref("");
const debugErr = ref("");
const showPrivacyGate = ref(false);
const privacyContractName = ref("《用户隐私保护指引》");

// 目标设备信息
const targetDeviceId = ref("");
const connectedDeviceName = ref("");
const connectedDeviceId = ref("");

// Wi-Fi 字段
const wifiSsid = ref("");
const wifiPassword = ref("");
const showPassword = ref(false);
const sendingConfig = ref(false);

// 状态监控日志
const logs = ref<{ time: string; text: string; type: 'info' | 'success' | 'error' }[]>([]);
const provStatus = ref<'pending' | 'success' | 'fail'>('pending');
const failureReason = ref("");
const showConsoleLogs = ref(false);

function getSignalText(rssi: number): string {
  if (rssi >= -60) return "极佳";
  if (rssi >= -75) return "一般";
  return "较弱";
}

function getSignalColor(rssi: number): string {
  if (rssi >= -60) return "#2f604f";
  if (rssi >= -75) return "#d97706";
  return "#82786d";
}

// ESP-IDF protocomm 配网客户端（页面同级 import；mp-weixin 禁止 import() 延迟加载）
let provisionClient: EspIdfProvisionClient | null = null;

let timeoutTimer: number | null = null;
let scanTimeoutTimer: number | null = null;

onMounted(() => {
  // 读取历史 Wi-Fi 并自动回填
  const lastSsid = uni.getStorageSync("last_wifi_ssid");
  const lastPassword = uni.getStorageSync("last_wifi_password");
  if (lastSsid) {
    wifiSsid.value = lastSsid;
  }
  if (lastPassword) {
    wifiPassword.value = lastPassword;
  }

  setPrivacyGateHandler(async () => {
    privacyContractName.value = await loadPrivacyContractName();
    showPrivacyGate.value = true;
  });
});

onUnmounted(() => {
  setPrivacyGateHandler(null);
  clearScanTimeout();
});

// 退出或隐藏时清理资源（onHide 不关闭 adapter，避免二次进入失败）
onHide(() => {
  stopBluetoothOperations(false);
});

onUnload(() => {
  stopBluetoothOperations(true);
});

function addLog(text: string, type: 'info' | 'success' | 'error' = 'info') {
  const now = new Date();
  const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;
  logs.value.push({ time: timeStr, text, type });
}

function clearScanTimeout() {
  if (scanTimeoutTimer) {
    clearTimeout(scanTimeoutTimer);
    scanTimeoutTimer = null;
  }
}

function finishScanning() {
  isScanning.value = false;
  markBluetoothDiscoveryStopped();
  void stopBluetoothDiscovery();
}

function stopScan() {
  clearScanTimeout();
  finishScanning();
  if (discoveredDevices.value.length === 0) {
    errorMsg.value = scanNoDeviceError;
  }
}

function startScanTimeout() {
  clearScanTimeout();
  scanTimeoutTimer = setTimeout(() => {
    if (!isScanning.value) {
      return;
    }
    finishScanning();
    if (discoveredDevices.value.length === 0) {
      errorMsg.value = scanNoDeviceTimeoutError;
    }
  }, BLE_SCAN_DURATION_MS) as unknown as number;
}

function stopBluetoothOperations(closeAdapter = false) {
  clearScanTimeout();
  if (isScanning.value) {
    finishScanning();
  } else {
    markBluetoothDiscoveryStopped();
    void stopBluetoothDiscovery();
  }
  uni.offBluetoothDeviceFound();
  if (connectedDeviceId.value) {
    uni.closeBLEConnection({
      deviceId: connectedDeviceId.value
    });
    connectedDeviceId.value = "";
  }
  if (closeAdapter) {
    closeBleAdapter();
  }
  if (timeoutTimer) {
    clearTimeout(timeoutTimer);
    timeoutTimer = null;
  }
  provisionClient = null;
}

// === 步骤 1: 扫描蓝牙与连接 ===

async function showPrivacyGateIfNeeded(): Promise<boolean> {
  const privacy = await checkBlePrivacyNeeded();
  if (!privacy.needed) {
    return false;
  }
  privacyContractName.value = privacy.contractName;
  showPrivacyGate.value = true;
  return true;
}

async function continueScanAfterPrivacy(skipPrivacyCheck = false) {
  errorMsg.value = "";
  debugErr.value = "";
  discoveredDevices.value = [];
  isScanning.value = true;

  try {
    await ensureBleReady({ skipPrivacyCheck });
    await performDiscovery();
  } catch (err) {
    isScanning.value = false;
    if (err instanceof PrivacyBackendError || err instanceof PrivacyDeniedError) {
      errorMsg.value = mapPrivacyError(err);
      return;
    }
    if (err instanceof PrivacyNeedAgreeError) {
      privacyContractName.value = err.privacyContractName;
      showPrivacyGate.value = true;
      return;
    }
    if (shouldShowPrivacyGateForBleError(err)) {
      privacyContractName.value = await loadPrivacyContractName();
      showPrivacyGate.value = true;
      return;
    }
    errorMsg.value = mapPrivacyError(err) || mapBleError(err);
    const detail = getBleDebugDetail(err);
    if (detail) {
      debugErr.value = detail;
    }
  }
}

async function startScan() {
  isScanning.value = false;
  errorMsg.value = "";
  debugErr.value = "";

  if (await showPrivacyGateIfNeeded()) {
    return;
  }

  await continueScanAfterPrivacy();
}

async function performDiscovery() {
  uni.offBluetoothDeviceFound();
  await startBluetoothDiscovery();
  addLog("开始搜索附近蓝牙设备...");
  listenBluetoothDevices();
  startScanTimeout();
}

function onPrivacyAgreed() {
  notifyPrivacyAgreed(PRIVACY_AGREE_BUTTON_ID);
  showPrivacyGate.value = false;
  void continueScanAfterPrivacy(true);
}

function onPrivacyDisagree() {
  notifyPrivacyDenied();
  showPrivacyGate.value = false;
  isScanning.value = false;
  errorMsg.value = mapPrivacyError(new PrivacyDeniedError());
}

async function onOpenPrivacyContract() {
  try {
    await openPrivacyContract();
  } catch {
    uni.showToast({ title: "无法打开隐私指引", icon: "none" });
  }
}

function listenBluetoothDevices() {
  uni.onBluetoothDeviceFound((res) => {
    res.devices.forEach((device) => {
      // 检查设备广播的 Service UUID 中是否包含我们的配网服务
      const serviceUuids = (device.advertisServiceUUIDs || []).map((u) =>
        u.toLowerCase().replace(/-/g, ""),
      );
      const targetServiceUuid = "1775244D-6B43-439B-877C-060F2D9BED07"
        .toLowerCase()
        .replace(/-/g, "");
      const hasProvService = serviceUuids.includes(targetServiceUuid);

      // 如果既不符合普通的过滤条件，也没有广播我们的配网服务，则丢弃
      if (!shouldIncludeBleDevice(device) && !hasProvService) {
        return;
      }

      const rawName = getBleAdvertisedName(device);
      let listName = getBleDeviceListName(device);

      // 如果设备确定是我们的配网设备，但因为各种原因没有广播名字，自动重命名以方便连接
      if (!rawName && hasProvService) {
        const id = String(device.deviceId || "").trim();
        const suffix = id.length > 8 ? id.slice(-8) : id;
        listName = `初心设备 (无广播名 · ${suffix})`;
      }

      const existing = discoveredDevices.value.find((x) => x.deviceId === device.deviceId);
      if (existing) {
        existing.RSSI = device.RSSI ?? existing.RSSI;
        existing.name = listName;
        existing.rawName = rawName;
      } else {
        discoveredDevices.value.push({
          deviceId: device.deviceId,
          name: listName,
          rawName,
          RSSI: device.RSSI ?? -100,
        });
      }
      discoveredDevices.value = sortDiscoveredDevices(discoveredDevices.value);
      debugErr.value = `已发现 ${discoveredDevices.value.length} ${scanFoundDebugLabel}`;
    });
  });
}

async function connectDevice(device: BleDeviceItem) {
  if (targetDeviceId.value) return;
  targetDeviceId.value = device.deviceId;
  errorMsg.value = "";
  debugErr.value = "开始连接...";

  // await 停止扫描，再等 200ms 让 Android BLE 栈稳定
  // 不 await 直接连接会导致 Android 上 createBLEConnection:fail connect timeout
  clearScanTimeout();
  await stopBluetoothDiscovery();
  markBluetoothDiscoveryStopped();
  isScanning.value = false;
  await new Promise<void>((r) => setTimeout(r, 200));

  const displayName = device.name;
  const deviceCode = device.rawName || displayName;
  addLog(`尝试建立蓝牙连接: ${displayName}`);
  uni.createBLEConnection({
    deviceId: device.deviceId,
    timeout: 10000,
    success: () => {
      connectedDeviceId.value = device.deviceId;
      connectedDeviceName.value = deviceCode;
      addLog(
        `蓝牙连接成功，建立 ESP-IDF Security1 会话（设备=${deviceCode}，PoP=${PROVISION_POP}）...`,
        "success",
      );
      void (async () => {
        try {
          provisionClient = new EspIdfProvisionClient(
            device.deviceId,
            PROVISION_POP,
            undefined,
            (msg) => {
              addLog(msg, "info");
              debugErr.value += "\n" + msg;
            }
          );
          await provisionClient.establishSession();
          addLog("安全会话建立成功", "success");
          currentStep.value = 2;
          targetDeviceId.value = "";
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          addLog(`安全会话建立失败: ${message}`, "error");
          errorMsg.value = message || "设备安全通道握手失败，请确认选择了正确的初心设备。";
          targetDeviceId.value = "";
          provisionClient = null;
          uni.closeBLEConnection({ deviceId: device.deviceId });
          connectedDeviceId.value = "";
          connectedDeviceName.value = "";
        }
      })();
    },
    fail: (err) => {
      targetDeviceId.value = "";
      errorMsg.value = `蓝牙连接失败: ${err.errMsg}`;
      addLog(`蓝牙连接失败: ${err.errMsg}`, "error");
    },
  });
}

// === 步骤 2: 输入 Wi-Fi 并发送 ===

function togglePasswordVisible() {
  showPassword.value = !showPassword.value;
}

function backToStep1() {
  stopBluetoothOperations(true);
  currentStep.value = 1;
  errorMsg.value = "";
  debugErr.value = "";
  targetDeviceId.value = "";
  connectedDeviceName.value = "";
  wifiSsid.value = "";
  wifiPassword.value = "";
  sendingConfig.value = false;
  provStatus.value = "pending";
  failureReason.value = "";
}

function scanLocalWifi() {
  uni.startWifi({
    success: () => {
      uni.getWifiList({
        success: () => {
          uni.onGetWifiList((res) => {
            if (res.wifiList && res.wifiList.length > 0) {
              // 选取信号最好的前几个 Wi-Fi 弹窗供用户选择
              const list = res.wifiList
                .filter(x => x.SSID)
                .slice(0, 8)
                .map(x => x.SSID);
              
              uni.showActionSheet({
                itemList: list,
                success: (sheetRes) => {
                  wifiSsid.value = list[sheetRes.tapIndex];
                }
              });
            } else {
              uni.showToast({ title: "未获取到 Wi-Fi，请手动输入", icon: "none" });
            }
          });
        },
        fail: () => {
          uni.showToast({ title: "扫描 Wi-Fi 列表失败", icon: "none" });
        }
      });
    },
    fail: (err) => {
      uni.showToast({ title: "请先开启手机 Wi-Fi 开关", icon: "none" });
    }
  });
}

function sendWifiCredentials() {
  if (!wifiSsid.value || !provisionClient) return;
  sendingConfig.value = true;
  errorMsg.value = "";

  // 记忆用户历史 Wi-Fi
  uni.setStorageSync("last_wifi_ssid", wifiSsid.value);
  uni.setStorageSync("last_wifi_password", wifiPassword.value);

  logs.value = [];
  currentStep.value = 3;
  provStatus.value = "pending";
  addLog(`开始配置设备 Wi-Fi，网络名: ${wifiSsid.value}`);
  startTimeoutTimer();

  provisionClient
    .provisionWifi(wifiSsid.value, wifiPassword.value, (status: WifiProvisionStatus) => {
      handleEspWifiStatus(status);
    })
    .then(() => {
      finishProvisionSuccess();
    })
    .catch((err: Error) => {
      addLog(`配网失败: ${err.message}`, "error");
      provStatus.value = "fail";
      failureReason.value = err.message || "设备网络连接失败，请确认无线网络可正常使用。";
      if (timeoutTimer) clearTimeout(timeoutTimer);
      sendingConfig.value = false;
    });
}

function handleEspWifiStatus(status: WifiProvisionStatus) {
  const message = mapWifiStatusToMessage(status);
  if (status === "connecting") {
    addLog(message);
    return;
  }
  if (status === "connected") {
    addLog(message, "success");
    return;
  }
  if (status === "failed_auth" || status === "failed_not_found" || status === "failed") {
    addLog(message, "error");
  }
}

function finishProvisionSuccess() {
  addLog("设备联网成功！获取 IP 地址成功。", "success");
  provStatus.value = "success";
  sendingConfig.value = false;
  if (timeoutTimer) clearTimeout(timeoutTimer);

  const deviceCode = extractDeviceCodeFromBleName(connectedDeviceName.value);
  if (deviceCode) {
    uni.setStorageSync("temp_device_code", deviceCode);
    addLog(`成功检测到设备码: ${deviceCode}，正在返回绑定页...`, "success");
  } else {
    addLog("配网成功，未能从蓝牙名解析设备码，请返回绑定页手动输入。", "success");
  }

  setTimeout(() => {
    stopBluetoothOperations(true);
    uni.switchTab({
      url: "/pages/index/index",
      fail: () => {
        uni.reLaunch({ url: "/pages/index/index" });
      },
    });
  }, 2000);
}

// === 步骤 3: 状态反馈与跳转处理 ===

function startTimeoutTimer() {
  if (timeoutTimer) clearTimeout(timeoutTimer);
  timeoutTimer = setTimeout(() => {
    if (provStatus.value === "pending") {
      addLog("设备响应超时，60秒内未完成联网配置", "error");
      provStatus.value = "fail";
      failureReason.value = "配网超时，请确认 Wi-Fi 密码正确并重试。";
      sendingConfig.value = false;
      stopBluetoothOperations();
    }
  }, 60000) as unknown as number;
}

function retryProvisioning() {
  stopBluetoothOperations(true);
  sendingConfig.value = false;
  currentStep.value = 1;
  errorMsg.value = "";
  debugErr.value = "";
  targetDeviceId.value = "";
  connectedDeviceName.value = "";
  connectedDeviceId.value = "";
  discoveredDevices.value = [];
  provStatus.value = "pending";
  failureReason.value = "";
  isScanning.value = false;
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 48rpx 34rpx 64rpx;
  background:
    radial-gradient(circle at 82% 0%, rgba(224, 114, 83, 0.14), transparent 34%),
    linear-gradient(180deg, #f8f1e7 0%, #f4eee8 48%, #ece7df 100%);
  box-sizing: border-box;
}

.hero {
  padding: 18rpx 4rpx 28rpx;
}

.eyebrow {
  color: #9b6146;
  font-size: 22rpx;
  letter-spacing: 2rpx;
  margin-bottom: 12rpx;
}

.title {
  color: #24211c;
  font-size: 50rpx;
  font-weight: 700;
  line-height: 1.12;
}

.subtitle {
  color: #6f665b;
  font-size: 26rpx;
  line-height: 1.6;
  margin-top: 14rpx;
}

/* 步骤指示器样式 */
.steps-indicator {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 30rpx 20rpx;
  margin-bottom: 30rpx;
}

.step-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
  z-index: 2;
}

.step-num {
  width: 50rpx;
  height: 50rpx;
  border-radius: 50%;
  background: #ece7df;
  color: #82786d;
  font-size: 24rpx;
  font-weight: bold;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease;
}

.step-text {
  font-size: 20rpx;
  color: #82786d;
  margin-top: 8rpx;
  font-weight: 500;
}

.step-node.active .step-num {
  background: #2f604f;
  color: #fff;
}

.step-node.active .step-text {
  color: #2f604f;
  font-weight: bold;
}

.step-node.completed .step-num {
  background: #e4eee8;
  color: #2f604f;
}

.step-line {
  flex: 1;
  height: 4rpx;
  background: #ece7df;
  margin: 0 16rpx;
  transform: translateY(-16rpx);
  transition: all 0.3s ease;
}

.step-line.active {
  background: #2f604f;
}

/* 面板样式 */
.panel {
  padding: 34rpx;
  background: rgba(255, 252, 246, 0.94);
  border: 1rpx solid rgba(128, 94, 69, 0.16);
  border-radius: 24rpx;
  box-shadow: 0 18rpx 50rpx rgba(70, 48, 32, 0.08);
}

.panel-header {
  margin-bottom: 24rpx;
  border-bottom: 1rpx solid rgba(128, 94, 69, 0.1);
  padding-bottom: 20rpx;
}

.panel-title {
  font-size: 32rpx;
  font-weight: bold;
  color: #24211c;
}

.panel-desc {
  font-size: 24rpx;
  color: #82786d;
  margin-top: 8rpx;
  line-height: 1.5;
}

/* 扫描区域 */
.scan-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 24rpx 0 8rpx;
  width: 100%;
}

.scan-idle {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
}

.scan-hint {
  font-size: 24rpx;
  color: #82786d;
  margin-top: 24rpx;
  margin-bottom: 8rpx;
  text-align: center;
  line-height: 1.5;
}

.scan-active {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
}

.scan-summary {
  font-size: 24rpx;
  color: #6f665b;
  margin-bottom: 20rpx;
}

.stop-scan {
  width: 220rpx;
  height: 72rpx;
  line-height: 72rpx;
  font-size: 24rpx;
  margin-bottom: 8rpx;
}

.radar-box {
  position: relative;
  width: 380rpx;
  min-height: 380rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 20rpx 0;
}

/* 扫描中动画圈 */
.radar-circle {
  position: absolute;
  border: 2rpx solid rgba(47, 96, 79, 0.3);
  border-radius: 50%;
  animation: radar-pulse 2s infinite linear;
}

.c1 { width: 180rpx; height: 180rpx; animation-delay: 0s; }
.c2 { width: 280rpx; height: 280rpx; animation-delay: 0.6s; }
.c3 { width: 380rpx; height: 380rpx; animation-delay: 1.2s; }

.breathing-glow-inner {
  position: absolute;
  width: 120rpx;
  height: 120rpx;
  border-radius: 50%;
  background: rgba(47, 96, 79, 0.08);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: breathing 3s infinite ease-in-out;
  z-index: 5;
}

.radar-search-icon {
  font-size: 52rpx;
}

.radar-status {
  position: absolute;
  bottom: 0;
  font-size: 24rpx;
  color: #2f604f;
  font-weight: 500;
  text-align: center;
  z-index: 5;
}

/* 虚线环圈轨道 */
.radar-orbit {
  position: absolute;
  border: 2rpx dashed rgba(47, 96, 79, 0.15);
  border-radius: 50%;
}

.radar-orbit.o1 {
  width: 300rpx;
  height: 300rpx;
}

.radar-orbit.o2 {
  width: 370rpx;
  height: 370rpx;
}

/* 绿色实体大盘片 */
.scan-plate-btn {
  width: 230rpx;
  height: 230rpx;
  border-radius: 50%;
  background: linear-gradient(135deg, #38705d, #2f604f);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  box-shadow: 0 12rpx 32rpx rgba(47, 96, 79, 0.35);
  color: #ffffff;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  z-index: 10;
}

.scan-plate-btn:active {
  transform: scale(0.95);
  box-shadow: 0 4rpx 12rpx rgba(47, 96, 79, 0.2);
}

.plate-icon {
  font-size: 56rpx;
  margin-bottom: 6rpx;
}

.plate-text {
  font-size: 24rpx;
  font-weight: bold;
  letter-spacing: 2rpx;
}

/* 列表样式 */
.device-list {
  width: 100%;
  max-height: 480rpx;
  margin-top: 30rpx;
  border-top: 1rpx solid rgba(128, 94, 69, 0.08);
  padding-top: 16rpx;
}

.empty-list {
  text-align: center;
  font-size: 24rpx;
  color: #82786d;
  padding: 48rpx 0;
}

/* 设备卡片式结构 */
.device-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 28rpx 24rpx;
  border: 1rpx solid rgba(128, 94, 69, 0.1);
  border-radius: 20rpx;
  margin-bottom: 16rpx;
  background: #ffffff;
  box-shadow: 0 4rpx 12rpx rgba(128, 94, 69, 0.03);
  transition: all 0.2s ease;
}

.device-item:active {
  background: rgba(47, 96, 79, 0.04);
  transform: translateY(1rpx);
}

.device-item.connecting {
  background: rgba(47, 96, 79, 0.06);
  border-color: rgba(47, 96, 79, 0.2);
}

.device-name-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.device-name {
  font-size: 28rpx;
  font-weight: bold;
  color: #24211c;
}

.device-tag {
  font-size: 18rpx;
  padding: 2rpx 10rpx;
  border-radius: 6rpx;
  font-weight: bold;
}

.device-tag.my-chuxin {
  background: #2f604f;
  color: #ffffff;
}

.device-tag.test-device {
  background: #e0f2fe;
  color: #0369a1;
}

.device-rssi-row {
  display: flex;
  align-items: center;
  gap: 10rpx;
  margin-top: 8rpx;
}

.device-signal-bar {
  font-size: 22rpx;
  font-weight: bold;
}

.device-rssi-value {
  font-size: 20rpx;
  color: #82786d;
}

.action-text {
  font-size: 24rpx;
  color: #2f604f;
  font-weight: 500;
}

.action-text.connecting {
  color: #9b6146;
}

/* 开发者调试日志 */
.dev-log-section {
  margin-top: 30rpx;
  border-top: 1rpx solid rgba(128, 94, 69, 0.06);
  padding-top: 15rpx;
  width: 100%;
}

.dev-log-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12rpx 8rpx;
  background: transparent;
}

.dev-log-title {
  font-size: 22rpx;
  color: #82786d;
  font-weight: bold;
}

.dev-log-arrow {
  font-size: 20rpx;
  color: #82786d;
}

.connected-highlight {
  color: #2f604f;
  font-weight: bold;
}

/* 表单组件 */
.form-group {
  margin-top: 20rpx;
  width: 100%;
}

.label {
  color: #82786d;
  font-size: 24rpx;
  margin-bottom: 12rpx;
}

.input {
  background: #fdfaf5;
  border: 1rpx solid rgba(128, 94, 69, 0.16);
  border-radius: 12rpx;
  padding: 0 24rpx;
  height: 80rpx;
  font-size: 28rpx;
  color: #24211c;
  flex: 1;
}

.wifi-input-row {
  display: flex;
  gap: 16rpx;
  align-items: center;
}

.mini.get-wifi {
  flex: 0 0 160rpx;
  height: 80rpx;
  line-height: 80rpx;
  font-size: 24rpx;
  background: #e4eee8;
  color: #2f604f;
}

.password-input-row {
  display: flex;
  position: relative;
  align-items: center;
}

.eye-icon {
  position: absolute;
  right: 24rpx;
  padding: 10rpx;
  font-size: 32rpx;
  z-index: 10;
}

/* 按钮及操作 */
.actions {
  display: flex;
  gap: 20rpx;
  margin-top: 40rpx;
}

button {
  flex: 1;
  height: 84rpx;
  line-height: 84rpx;
  font-size: 26rpx;
}

.primary {
  color: #fff;
  background: #2f604f;
}

.ghost {
  color: #2f604f;
  background: #e4eee8;
}

.message {
  margin-top: 24rpx;
  padding: 16rpx 20rpx;
  border-radius: 12rpx;
  font-size: 24rpx;
}

.message.error {
  background: #f3ded9;
  color: #9e3b35;
  border: 1rpx solid rgba(158, 59, 53, 0.15);
}

.message.debug {
  background: #ece7df;
  color: #5a544e;
  border: 1rpx solid rgba(90, 84, 78, 0.12);
  font-size: 20rpx;
  font-family: ui-monospace, SFMono-Regular, monospace;
  word-break: break-all;
}

/* 状态控制台 */
.console-box {
  background: #1c1815;
  border-radius: 16rpx;
  padding: 24rpx;
  margin-bottom: 30rpx;
}

.console-title {
  color: #8c857b;
  font-size: 20rpx;
  margin-bottom: 12rpx;
  font-family: ui-monospace, SFMono-Regular, monospace;
}

.console-log {
  height: 200rpx;
}

.log-line {
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 22rpx;
  line-height: 1.5;
  margin-bottom: 8rpx;
  color: #b5ada3;
}

.log-line.success {
  color: #55b28b;
}

.log-line.error {
  color: #f17872;
}

.log-time {
  margin-right: 12rpx;
  color: #5a544e;
}

/* 状态面板 */
.status-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 30rpx 0 10rpx;
  text-align: center;
}

.status-icon {
  width: 90rpx;
  height: 90rpx;
  border-radius: 50%;
  font-size: 40rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 20rpx;
}

.success .status-icon {
  background: #e4eee8;
  color: #2f604f;
}

.fail .status-icon {
  background: #f3ded9;
  color: #9e3b35;
}

.status-title {
  font-size: 30rpx;
  font-weight: bold;
  color: #24211c;
  margin-bottom: 8rpx;
}

.status-desc {
  font-size: 24rpx;
  color: #82786d;
  line-height: 1.5;
  padding: 0 40rpx;
}

.retry-btn {
  margin-top: 30rpx;
  width: 240rpx;
  height: 76rpx;
  line-height: 76rpx;
  font-size: 24rpx;
}

.spinner {
  width: 60rpx;
  height: 60rpx;
  border: 4rpx solid rgba(47, 96, 79, 0.1);
  border-left-color: #2f604f;
  border-radius: 50%;
  animation: spin 1s infinite linear;
  margin-bottom: 20rpx;
}

/* 关键帧动画 */
@keyframes radar-pulse {
  0% { transform: scale(0.4); opacity: 1; }
  100% { transform: scale(1.1); opacity: 0; }
}

@keyframes breathing {
  0% { transform: scale(0.94); opacity: 0.8; }
  50% { transform: scale(1.06); opacity: 1; }
  100% { transform: scale(0.94); opacity: 0.8; }
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.privacy-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(36, 33, 28, 0.45);
  padding: 40rpx;
  box-sizing: border-box;
}

.privacy-card {
  width: 100%;
  max-width: 620rpx;
  background: #fffaf3;
  border-radius: 24rpx;
  padding: 40rpx 36rpx 32rpx;
  border: 1rpx solid rgba(128, 94, 69, 0.16);
}

.privacy-title {
  font-size: 34rpx;
  font-weight: 700;
  color: #24211c;
  margin-bottom: 20rpx;
}

.privacy-desc {
  font-size: 26rpx;
  line-height: 1.6;
  color: #6f665b;
  margin-bottom: 16rpx;
}

.privacy-hint {
  font-size: 22rpx;
  line-height: 1.5;
  color: #9b6146;
  margin-bottom: 28rpx;
}

.privacy-link {
  color: #2f604f;
  text-decoration: underline;
}

.privacy-actions {
  display: flex;
  gap: 20rpx;
}

.privacy-actions button {
  flex: 1;
  height: 80rpx;
  line-height: 80rpx;
  font-size: 26rpx;
}
</style>
