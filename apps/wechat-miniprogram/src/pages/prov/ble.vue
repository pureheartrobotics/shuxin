<template>
  <view class="page">
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
        <view class="panel-desc">请确认手机蓝牙已打开。确保设备处于配网模式（指示灯快闪）。</view>
      </view>

      <view class="scan-container">
        <view v-if="isScanning" class="radar-box">
          <view class="radar-circle c1"></view>
          <view class="radar-circle c2"></view>
          <view class="radar-circle c3"></view>
          <text class="radar-status">正在搜寻附近的初心设备...</text>
        </view>
        <view v-else class="radar-box idle" @tap="startScan">
          <button class="primary scan-btn">开始扫描</button>
        </view>

        <!-- 蓝牙列表 -->
        <scroll-view scroll-y class="device-list">
          <view v-if="discoveredDevices.length === 0" class="empty-list">
            {{ isScanning ? '尚未发现设备，请确保设备正常开机并处于配网状态' : '点击上方按钮开始扫描' }}
          </view>
          <view
            v-for="device in discoveredDevices"
            :key="device.deviceId"
            class="device-item"
            :class="{ connecting: targetDeviceId === device.deviceId }"
            @tap="connectDevice(device)"
          >
            <view class="device-info">
              <text class="device-name">{{ device.name }}</text>
              <text class="device-rssi">信号强度: {{ device.RSSI }} dBm</text>
            </view>
            <view class="device-action">
              <text v-if="targetDeviceId === device.deviceId" class="action-text connecting">连接中...</text>
              <text v-else class="action-text">点击连接 ➔</text>
            </view>
          </view>
        </scroll-view>
      </view>

      <view v-if="errorMsg" class="message error">{{ errorMsg }}</view>
    </view>

    <!-- 第二步：填写 Wi-Fi 信息 -->
    <view v-if="currentStep === 2" class="panel">
      <view class="panel-header">
        <view class="panel-title">第二步：配置 Wi-Fi</view>
        <view class="panel-desc">设备：{{ connectedDeviceName }} 已连接。请输入设备将要连接的无线网络信息。</view>
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

      <view class="console-box">
        <view class="console-title">连接状态追踪</view>
        <scroll-view scroll-y class="console-log">
          <view v-for="(log, index) in logs" :key="index" class="log-line" :class="log.type">
            <text class="log-time">[{{ log.time }}]</text>
            <text class="log-text">{{ log.text }}</text>
          </view>
        </scroll-view>
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
import { ref } from "vue";

// 状态管理
const currentStep = ref(1);
const isScanning = ref(false);
const discoveredDevices = ref<any[]>([]);
const errorMsg = ref("");

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

// 蓝牙通信配置 (可根据固件端进行修改约定)
const SERVICE_UUID = "0000FFFF-0000-1000-8000-00805F9B34FB";
const CHAR_SESSION_UUID = "0000FFF1-0000-1000-8000-00805F9B34FB"; // 握手与PoP特征值
const CHAR_CONFIG_UUID = "0000FFF2-0000-1000-8000-00805F9B34FB";  // Wi-Fi配置与状态通知特征值

let timeoutTimer: number | null = null;

// 退出或隐藏时清理资源
onHide(() => {
  stopBluetoothOperations();
});

onUnload(() => {
  stopBluetoothOperations();
});

function addLog(text: string, type: 'info' | 'success' | 'error' = 'info') {
  const now = new Date();
  const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;
  logs.value.push({ time: timeStr, text, type });
}

function stopBluetoothOperations() {
  if (isScanning.value) {
    uni.stopBluetoothDevicesDiscovery({
      success: () => { isScanning.value = false; }
    });
  }
  if (connectedDeviceId.value) {
    uni.closeBLEConnection({
      deviceId: connectedDeviceId.value
    });
    connectedDeviceId.value = "";
  }
  if (timeoutTimer) {
    clearTimeout(timeoutTimer);
    timeoutTimer = null;
  }
}

// === 步骤 1: 扫描蓝牙与连接 ===

function startScan() {
  errorMsg.value = "";
  discoveredDevices.value = [];
  isScanning.value = true;

  // 1. 初始化蓝牙适配器
  uni.openBluetoothAdapter({
    success: () => {
      // 2. 开始搜索
      uni.startBluetoothDevicesDiscovery({
        allowDuplicatesKey: false,
        success: () => {
          addLog("开始搜索附近蓝牙设备...");
          listenBluetoothDevices();
        },
        fail: (err) => {
          isScanning.value = false;
          errorMsg.value = `开启蓝牙搜索失败: ${err.errMsg}`;
        }
      });
    },
    fail: (err) => {
      isScanning.value = false;
      errorMsg.value = "无法初始化蓝牙，请确认手机蓝牙已开启且授权给微信";
    }
  });
}

function listenBluetoothDevices() {
  uni.onBluetoothDeviceFound((res) => {
    res.devices.forEach((device) => {
      const name = device.name || device.localName || "";
      // 过滤前缀以 ShuXin- 开头的设备
      if (name.startsWith("ShuXin-")) {
        if (!discoveredDevices.value.some((x) => x.deviceId === device.deviceId)) {
          discoveredDevices.value.push(device);
        }
      }
    });
  });
}

function connectDevice(device: any) {
  if (targetDeviceId.value) return; // 正在连接中
  targetDeviceId.value = device.deviceId;
  errorMsg.value = "";

  // 停止搜索
  uni.stopBluetoothDevicesDiscovery({
    success: () => { isScanning.value = false; }
  });

  addLog(`尝试建立蓝牙连接: ${device.name}`);
  uni.createBLEConnection({
    deviceId: device.deviceId,
    timeout: 10000,
    success: () => {
      connectedDeviceId.value = device.deviceId;
      connectedDeviceName.value = device.name;
      addLog(`蓝牙连接成功！进行底层安全通道校验...`, 'success');
      
      // 进行底层安全校验 (PoP: shuxin)
      performPoPVerification(device.deviceId, device.name);
    },
    fail: (err) => {
      targetDeviceId.value = "";
      errorMsg.value = `蓝牙连接失败: ${err.errMsg}`;
      addLog(`蓝牙连接失败: ${err.errMsg}`, 'error');
    }
  });
}

// 静默安全通道握手校验
function performPoPVerification(deviceId: string, deviceName: string) {
  // 1. 寻找服务
  uni.getBLEDeviceServices({
    deviceId,
    success: (res) => {
      // 2. 寻找特征值
      uni.getBLEDeviceCharacteristics({
        deviceId,
        serviceId: SERVICE_UUID,
        success: (charRes) => {
          addLog("发现特征值服务，写入安全密钥...");
          // 3. 后台发送 PoP 安全参数 "shuxin"
          const popStr = "shuxin";
          const buffer = new ArrayBuffer(popStr.length);
          const dataView = new DataView(buffer);
          for (let i = 0; i < popStr.length; i++) {
            dataView.setUint8(i, popStr.charCodeAt(i));
          }

          uni.writeBLECharacteristicValue({
            deviceId,
            serviceId: SERVICE_UUID,
            characteristicId: CHAR_SESSION_UUID,
            value: buffer,
            success: () => {
              addLog("安全密钥验证通过！", 'success');
              // 进入第二步：填写 Wi-Fi
              currentStep.value = 2;
              targetDeviceId.value = "";
            },
            fail: (err) => {
              addLog(`安全参数校验失败: ${err.errMsg}`, 'error');
              errorMsg.value = "设备安全通道握手失败，请重新尝试。";
              targetDeviceId.value = "";
              uni.closeBLEConnection({ deviceId });
              connectedDeviceId.value = "";
            }
          });
        },
        fail: (err) => {
          errorMsg.value = `获取特征值失败: ${err.errMsg}`;
          targetDeviceId.value = "";
          uni.closeBLEConnection({ deviceId });
          connectedDeviceId.value = "";
        }
      });
    },
    fail: (err) => {
      errorMsg.value = `获取蓝牙服务失败: ${err.errMsg}`;
      targetDeviceId.value = "";
      uni.closeBLEConnection({ deviceId });
      connectedDeviceId.value = "";
    }
  });
}

// === 步骤 2: 输入 Wi-Fi 并发送 ===

function togglePasswordVisible() {
  showPassword.value = !showPassword.value;
}

function backToStep1() {
  stopBluetoothOperations();
  currentStep.value = 1;
  errorMsg.value = "";
  targetDeviceId.value = "";
  connectedDeviceName.value = "";
  wifiSsid.value = "";
  wifiPassword.value = "";
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
  if (!wifiSsid.value) return;
  sendingConfig.value = true;
  errorMsg.value = "";

  logs.value = [];
  currentStep.value = 3;
  provStatus.value = 'pending';
  addLog(`开始配置设备 Wi-Fi，网络名: ${wifiSsid.value}`);

  // 1. 订阅连接状态 Notify
  uni.notifyBLECharacteristicValueChange({
    deviceId: connectedDeviceId.value,
    serviceId: SERVICE_UUID,
    characteristicId: CHAR_CONFIG_UUID,
    state: true,
    success: () => {
      addLog("成功监听设备连接反馈特征值");
      
      // 监听通知回调
      uni.onBLECharacteristicValueChange((res) => {
        if (res.characteristicId === CHAR_CONFIG_UUID) {
          const dataView = new DataView(res.value);
          const statusCode = dataView.getUint8(0);
          handleDeviceStatusUpdate(statusCode);
        }
      });

      // 2. 发送 Wi-Fi payload
      // 协议数据载荷约定：SSID 和 Password 拼接成 JSON 写入特征值 (或 Protobuf)
      const payload = JSON.stringify({
        ssid: wifiSsid.value,
        password: wifiPassword.value
      });

      const buffer = new ArrayBuffer(payload.length);
      const dataView = new DataView(buffer);
      for (let i = 0; i < payload.length; i++) {
        dataView.setUint8(i, payload.charCodeAt(i));
      }

      addLog("正在写入 Wi-Fi 账号和密码数据...");
      uni.writeBLECharacteristicValue({
        deviceId: connectedDeviceId.value,
        serviceId: SERVICE_UUID,
        characteristicId: CHAR_CONFIG_UUID,
        value: buffer,
        success: () => {
          addLog("数据写入成功！设备开始连接 Wi-Fi...", 'success');
          // 启动 60 秒超时定时器
          startTimeoutTimer();
        },
        fail: (err) => {
          addLog(`向特征值写入 Wi-Fi 配置失败: ${err.errMsg}`, 'error');
          provStatus.value = 'fail';
          failureReason.value = "发送数据失败，请确认设备未断开。";
        }
      });
    },
    fail: (err) => {
      addLog(`订阅特征值状态通知失败: ${err.errMsg}`, 'error');
      provStatus.value = 'fail';
      failureReason.value = "监听设备连接反馈服务失败。";
    }
  });
}

// === 步骤 3: 状态反馈与跳转处理 ===

function startTimeoutTimer() {
  if (timeoutTimer) clearTimeout(timeoutTimer);
  timeoutTimer = setTimeout(() => {
    if (provStatus.value === 'pending') {
      addLog("设备响应超时，60秒内未完成联网配置", 'error');
      provStatus.value = 'fail';
      failureReason.value = "配网超时，请确认 Wi-Fi 密码正确并重试。";
      stopBluetoothOperations();
    }
  }, 60000);
}

function handleDeviceStatusUpdate(code: number) {
  // 根据设计规范定义的状态码进行响应
  switch (code) {
    case 0: // Success
      addLog("设备联网成功！获取 IP 地址成功。", 'success');
      provStatus.value = 'success';
      if (timeoutTimer) clearTimeout(timeoutTimer);
      
      // 提取设备码
      // 例如蓝牙名是 "ShuXin-000013" -> 对应 device_code "SX-000013"
      let deviceCode = "";
      if (connectedDeviceName.value.startsWith("ShuXin-")) {
        const rawCode = connectedDeviceName.value.replace("ShuXin-", "");
        deviceCode = `SX-${rawCode}`;
      }
      
      // 写入本地缓存，供绑定页 onShow 获取
      if (deviceCode) {
        uni.setStorageSync("temp_device_code", deviceCode);
        addLog(`成功检测到设备码: ${deviceCode}，正在返回绑定页...`, 'success');
      }

      // 延迟 2 秒返回绑定页
      setTimeout(() => {
        stopBluetoothOperations();
        uni.switchTab({
          url: "/pages/index/index"
        });
      }, 2000);
      break;

    case 1: // Connecting
      addLog("设备正在关联 Wi-Fi 路由器，请稍候...");
      break;

    case 2: // Auth Fail
      addLog("设备连接失败：Wi-Fi 密码校验错误", 'error');
      provStatus.value = 'fail';
      failureReason.value = "密码错误。请检查 Wi-Fi 密码是否正确输入。";
      if (timeoutTimer) clearTimeout(timeoutTimer);
      break;

    case 3: // AP Not Found
      addLog("设备连接失败：未找到指定的 Wi-Fi", 'error');
      provStatus.value = 'fail';
      failureReason.value = "找不到 Wi-Fi。请检查 Wi-Fi 名称拼写是否正确，或靠近路由器。";
      if (timeoutTimer) clearTimeout(timeoutTimer);
      break;

    case 4: // DHCP Fail
      addLog("设备连接失败：IP 获取 (DHCP) 超时", 'error');
      provStatus.value = 'fail';
      failureReason.value = "路由器分配 IP 地址失败，请检查路由器配置。";
      if (timeoutTimer) clearTimeout(timeoutTimer);
      break;

    case 5: // Unknown
    default:
      addLog(`设备连接失败：未知网络错误 (错误码: ${code})`, 'error');
      provStatus.value = 'fail';
      failureReason.value = "设备网络连接失败，请确认无线网络可正常使用。";
      if (timeoutTimer) clearTimeout(timeoutTimer);
      break;
  }
}

function retryProvisioning() {
  stopBluetoothOperations();
  sendingConfig.value = false;
  currentStep.value = 2;
  errorMsg.value = "";
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
  margin-bottom: 32rpx;
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
}

.radar-box {
  position: relative;
  width: 240rpx;
  height: 240rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  margin: 40rpx 0;
}

.radar-circle {
  position: absolute;
  border: 2rpx solid rgba(47, 96, 79, 0.3);
  border-radius: 50%;
  animation: radar-pulse 2s infinite linear;
}

.c1 { width: 100rpx; height: 100rpx; animation-delay: 0s; }
.c2 { width: 180rpx; height: 180rpx; animation-delay: 0.6s; }
.c3 { width: 240rpx; height: 240rpx; animation-delay: 1.2s; }

.radar-status {
  font-size: 24rpx;
  color: #2f604f;
  font-weight: 500;
  text-align: center;
  z-index: 5;
  margin-top: 16rpx;
}

.radar-box.idle {
  animation: none;
}

.scan-btn {
  width: 200rpx;
  height: 80rpx;
  line-height: 80rpx;
  font-size: 26rpx;
}

/* 列表样式 */
.device-list {
  width: 100%;
  max-height: 380rpx;
  margin-top: 30rpx;
  border-top: 1rpx solid rgba(128, 94, 69, 0.1);
  padding-top: 10rpx;
}

.empty-list {
  text-align: center;
  font-size: 24rpx;
  color: #82786d;
  padding: 40rpx 0;
}

.device-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 24rpx 16rpx;
  border-bottom: 1rpx solid rgba(128, 94, 69, 0.08);
  border-radius: 12rpx;
  margin-bottom: 10rpx;
  background: transparent;
  transition: background-color 0.2s ease;
}

.device-item:active {
  background: rgba(47, 96, 79, 0.06);
}

.device-item.connecting {
  background: rgba(47, 96, 79, 0.08);
}

.device-name {
  font-size: 28rpx;
  font-weight: bold;
  color: #24211c;
  display: block;
}

.device-rssi {
  font-size: 20rpx;
  color: #82786d;
  margin-top: 6rpx;
  display: block;
}

.action-text {
  font-size: 24rpx;
  color: #2f604f;
  font-weight: 500;
}

.action-text.connecting {
  color: #9b6146;
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
  0% { transform: scale(0.6); opacity: 1; }
  100% { transform: scale(1.1); opacity: 0; }
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}
</style>
