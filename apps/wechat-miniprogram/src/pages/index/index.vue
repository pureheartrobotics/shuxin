<template>
  <view class="page">
    <view class="hero">
      <view class="eyebrow">SHUXIN DEVICE</view>
      <view class="title">绑定你的舒心设备</view>
      <view class="subtitle">扫码或输入认领码，把设备交给当前微信用户。</view>
      <view class="auth-status">{{ authStatus }}</view>
    </view>

    <view class="panel">
      <view class="label">{{ bindCodeKind === "claim_code" ? "认领码" : "设备码" }}</view>
      <input class="input" v-model="bindCode" placeholder="扫码后自动填入外壳认领码" />
      <view class="actions">
        <button class="ghost" @tap="scanClaimCode">相机扫码</button>
        <button class="ghost" :disabled="loading" @tap="decodeBarcodeImage">传图识别</button>
        <button class="primary" :disabled="loading" @tap="bindDevice">绑定</button>
      </view>
      <view class="actions secondary-actions">
        <button class="ghost" :disabled="loading" @tap="checkBackendHealth">测试后端连接</button>
      </view>
      <view v-if="message" class="message" :class="resultKind">{{ message }}</view>
    </view>

    <view class="section-header">
      <view class="section-title">我的设备</view>
      <button class="mini" :disabled="loading" @tap="loadDevices">刷新</button>
    </view>
    <view v-if="devices.length === 0" class="empty">还没有绑定设备</view>
    <view v-for="device in devices" :key="device.binding_id" class="device">
      <view>
        <view class="device-code">{{ device.device_code || device.device_id }}</view>
        <view class="device-meta">{{ device.online ? "在线" : "离线" }} · {{ device.bound_at || "刚刚绑定" }}</view>
      </view>
      <button class="danger" :disabled="loading" @tap="unbindDevice(device)">解绑</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { onLoad } from "@dcloudio/uni-app";
import { ref } from "vue";

const apiBase = import.meta.env.VITE_SHUXIN_API_BASE || "http://localhost:8765";
const bindCode = ref("");
const bindCodeKind = ref<"device_code" | "claim_code">("claim_code");
const devices = ref<any[]>([]);
const loading = ref(false);
const message = ref("");
const authStatus = ref("等待获取微信身份");
const resultKind = ref<"success" | "error" | "info">("info");

onLoad((query: Record<string, string | undefined>) => {
  ensureLoggedIn();
  applyScannedCode(query?.device_code || query?.claim_code || "", query?.claim_code ? "claim_code" : "device_code");
});

function ensureLoggedIn() {
  const token = sessionToken();
  if (!token) {
    uni.redirectTo({ url: "/pages/login/login" });
    return;
  }
  authStatus.value = "微信身份已确认";
}

function sessionToken(): string {
  const token = String(uni.getStorageSync("shuxin_session_token") || "");
  const expiresAt = String(uni.getStorageSync("shuxin_session_expires_at") || "");
  if (!token) return "";
  if (expiresAt && Date.parse(expiresAt) <= Date.now()) return "";
  return token;
}

function request(path: string, data: Record<string, unknown>): Promise<any> {
  return new Promise((resolve, reject) => {
    uni.request({
      url: `${apiBase}${path}`,
      method: "POST",
      data,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300 && !res.data?.error) {
          resolve(res.data);
        } else {
          const errorText = res.data?.error || `请求失败: ${res.statusCode}`;
          reject(new Error(path === "/api/devices/bind" ? formatBindError(errorText) : errorText));
        }
      },
      fail: (error) => {
        reject(new Error(formatRequestError(error)));
      }
    });
  });
}

function requestGet(path: string): Promise<any> {
  return new Promise((resolve, reject) => {
    uni.request({
      url: `${apiBase}${path}`,
      method: "GET",
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300 && !res.data?.error) {
          resolve(res.data);
        } else {
          reject(new Error(res.data?.error || `请求失败: ${res.statusCode}`));
        }
      },
      fail: (error) => {
        reject(new Error(formatRequestError(error)));
      }
    });
  });
}

function formatRequestError(error: any): string {
  const raw = error?.errMsg || String(error || "");
  if (raw.includes("fail") || raw.includes("ERR_CONNECTION_REFUSED")) {
    return `无法连接后端 ${apiBase}，请确认 Docker voice 服务已启动，或用 SHUXIN_API_BASE 指定可访问地址后重新构建小程序`;
  }
  return raw || "请求失败";
}

function setMessage(kind: "success" | "error" | "info", text: string) {
  resultKind.value = kind;
  message.value = text;
}

function formatBindError(errorText: string): string {
  if (errorText.includes("already claimed") || errorText.includes("inactive")) {
    return "这个外壳认领码已经被绑定过。请先在当前用户下解绑，或在后台重置认领码后再绑定。";
  }
  if (errorText.includes("claim_code is invalid") || errorText.includes("claim_code or device_code is invalid")) {
    return "没有找到这个外壳认领码。请确认后台已生成并入库，且微信开发者工具连接的是同一个后端数据库。";
  }
  return `${errorText}。请确认扫码内容是机器人外壳条形码的认领码，不是设备密钥。`;
}

async function withSessionToken(fn: (token: string) => Promise<void>) {
  loading.value = true;
  setMessage("info", "");
  try {
    const token = sessionToken();
    if (!token) {
      uni.redirectTo({ url: "/pages/login/login" });
      return;
    }
    return await fn(token);
  } catch (error) {
    setMessage("error", error.message || String(error));
  } finally {
    loading.value = false;
  }
}

function scanClaimCode() {
  uni.scanCode({
    onlyFromCamera: true,
    scanType: ["barCode"],
    success: (res) => {
      applyScannedText(res.result || res.path || "");
    },
    fail: (error) => {
      setMessage("error", `${error.errMsg || "扫码失败"}。相机扫码只识别一维条形码；如果要上传图片，请点“传图识别”。`);
    }
  });
}

function decodeBarcodeImage() {
  uni.chooseImage({
    count: 1,
    sizeType: ["original"],
    success: async (res) => {
      const filePath = res.tempFilePaths?.[0] || "";
      if (!filePath) {
        setMessage("error", "没有选择条形码图片");
        return;
      }
      loading.value = true;
      setMessage("info", "");
      try {
        const imageBase64 = await readFileBase64(filePath);
        const result = await request("/api/barcodes/decode", { image_base64: imageBase64 });
        applyScannedCode(result.text || "", "claim_code");
        setMessage(result.text ? "success" : "error", result.text ? `识别成功: ${result.text}` : "未识别到条形码");
      } catch (error) {
        setMessage("error", error.message || String(error));
      } finally {
        loading.value = false;
      }
    },
    fail: (error) => {
      setMessage("error", error.errMsg || "没有选择图片");
    }
  });
}

function readFileBase64(filePath: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const fileSystem = (uni as any).getFileSystemManager?.();
    if (!fileSystem) {
      reject(new Error("当前平台不支持读取图片文件"));
      return;
    }
    fileSystem.readFile({
      filePath,
      encoding: "base64",
      success: (res: { data: string }) => resolve(res.data || ""),
      fail: (error: any) => reject(new Error(error.errMsg || "读取图片失败"))
    });
  });
}

async function checkBackendHealth() {
  loading.value = true;
  setMessage("info", "");
  try {
    const result = await requestGet("/health");
    setMessage("success", `后端连接正常: ${result.service || apiBase}`);
  } catch (error) {
    setMessage("error", error.message || String(error));
  } finally {
    loading.value = false;
  }
}

function applyScannedText(rawValue: string) {
  const raw = String(rawValue || "").trim();
  const deviceMatch = raw.match(/[?&]device_code=([^&]+)/);
  const claimMatch = raw.match(/[?&]claim_code=([^&]+)/);
  if (deviceMatch) {
    applyScannedCode(deviceMatch[1], "device_code");
    return;
  }
  if (claimMatch) {
    applyScannedCode(claimMatch[1], "claim_code");
    return;
  }
  applyScannedCode(raw.replace(/^device_code=/, "").replace(/^claim_code=/, ""), raw.startsWith("device_code=") ? "device_code" : "claim_code");
}

function applyScannedCode(value: string, kind: "device_code" | "claim_code") {
  const code = decodeURIComponent(String(value || "").trim());
  if (!code) return;
  bindCode.value = code;
  bindCodeKind.value = kind;
}

async function bindDevice() {
  if (!bindCode.value.trim()) {
    setMessage("error", "请先扫码或输入外壳认领码");
    return;
  }
  loading.value = true;
  setMessage("info", "");
  try {
    const token = sessionToken();
    if (!token) {
      uni.redirectTo({ url: "/pages/login/login" });
      return;
    }
    const result = await request("/api/devices/bind", buildBindPayload(token));
    setMessage("success", result.already_bound ? "设备已绑定" : `绑定成功: ${result.device_code || result.device_id || bindCode.value.trim()}`);
    uni.showToast({ title: "绑定成功", icon: "success" });
    bindCode.value = "";
    bindCodeKind.value = "claim_code";
    await loadDevices();
  } catch (error) {
    setMessage("error", `绑定失败: ${error.message || String(error)}`);
    uni.showToast({ title: "绑定失败", icon: "none" });
  } finally {
    loading.value = false;
  }
}

function buildBindPayload(token: string): Record<string, unknown> {
  const code = bindCode.value.trim();
  const kind = looksLikeClaimCode(code) ? "claim_code" : bindCodeKind.value;
  return {
    session_token: token,
    [kind]: code
  };
}

function looksLikeClaimCode(code: string): boolean {
  return /^CLM-[A-Za-z0-9]+-[A-Za-z0-9]+$/.test(code.trim());
}

async function loadDevices() {
  await withSessionToken(async (token) => {
    const result = await request("/api/devices/my", { session_token: token });
    devices.value = result.items || [];
  });
}

async function unbindDevice(device: any) {
  await withSessionToken(async (token) => {
    await request("/api/devices/unbind", {
      session_token: token,
      device_code: device.device_code || device.device_id
    });
    setMessage("success", "已解绑");
    await loadDevices();
  });
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 48rpx 34rpx 64rpx;
  background:
    radial-gradient(circle at 12% 0%, rgba(224, 114, 83, 0.18), transparent 34%),
    linear-gradient(180deg, #f8f1e7 0%, #f4eee8 48%, #ece7df 100%);
}

.hero {
  padding: 28rpx 4rpx 36rpx;
}

.eyebrow {
  color: #9b6146;
  font-size: 22rpx;
  letter-spacing: 2rpx;
  margin-bottom: 14rpx;
}

.title {
  color: #24211c;
  font-size: 54rpx;
  font-weight: 700;
  line-height: 1.12;
}

.subtitle {
  color: #6f665b;
  font-size: 28rpx;
  line-height: 1.6;
  margin-top: 18rpx;
}

.auth-status {
  display: inline-flex;
  margin-top: 18rpx;
  padding: 8rpx 18rpx;
  color: #2f604f;
  background: rgba(228, 238, 232, 0.9);
  border-radius: 999rpx;
  font-size: 24rpx;
  line-height: 1.5;
}

.panel,
.device {
  background: rgba(255, 252, 246, 0.92);
  border: 1rpx solid rgba(128, 94, 69, 0.16);
  border-radius: 24rpx;
  box-shadow: 0 18rpx 50rpx rgba(70, 48, 32, 0.08);
}

.panel {
  padding: 28rpx;
}

.label,
.section-title {
  color: #4a4037;
  font-size: 28rpx;
  font-weight: 700;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18rpx;
  margin: 42rpx 4rpx 18rpx;
}

.input {
  height: 88rpx;
  margin-top: 18rpx;
  padding: 0 24rpx;
  border-radius: 18rpx;
  background: #ffffff;
  color: #25211c;
  font-size: 28rpx;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 18rpx;
  margin-top: 22rpx;
}

.secondary-actions {
  margin-top: 16rpx;
}

button {
  flex: 1;
  min-width: 180rpx;
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

.danger {
  flex: 0 0 132rpx;
  height: 68rpx;
  line-height: 68rpx;
  color: #9e3b35;
  background: #f3ded9;
  font-size: 24rpx;
}

.message {
  margin-top: 20rpx;
  color: #9b6146;
  font-size: 26rpx;
}

.message.success {
  color: #2f604f;
}

.message.error {
  color: #9e3b35;
}

.section-title {
  margin: 0;
}

.mini {
  flex: 0 0 128rpx;
  min-width: 128rpx;
  height: 62rpx;
  line-height: 62rpx;
  color: #2f604f;
  background: #e4eee8;
  font-size: 24rpx;
}

.empty {
  padding: 36rpx 0;
  color: #82786d;
  font-size: 28rpx;
}

.device {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20rpx;
  padding: 24rpx;
  margin-bottom: 18rpx;
}

.device-code {
  color: #25211c;
  font-size: 30rpx;
  font-weight: 700;
}

.device-meta {
  color: #82786d;
  font-size: 24rpx;
  margin-top: 8rpx;
}
</style>
