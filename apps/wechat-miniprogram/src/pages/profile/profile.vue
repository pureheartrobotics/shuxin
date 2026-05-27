<template>
  <view class="page">
    <view class="hero">
      <view class="eyebrow">SHUXIN ACCOUNT</view>
      <view class="title">个人中心</view>
      <view class="subtitle">{{ loggedIn ? "微信身份已登录" : "尚未登录" }}</view>
    </view>

    <view class="panel">
      <view class="row">
        <view>
          <view class="label">当前用户</view>
          <view class="value">{{ maskedUserId }}</view>
        </view>
      </view>
      <view class="row">
        <view>
          <view class="label">绑定设备</view>
          <view class="value">{{ deviceCount }} 台</view>
        </view>
        <button class="mini" :disabled="loading" @tap="loadProfile">刷新</button>
      </view>
      <button class="danger" @tap="logout">退出登录</button>
      <view v-if="message" class="message">{{ message }}</view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { onShow } from "@dcloudio/uni-app";
import { computed, ref } from "vue";

const apiBase = import.meta.env.VITE_SHUXIN_API_BASE || "http://localhost:8765";
const loading = ref(false);
const message = ref("");
const userId = ref("");
const deviceCount = ref(0);
const loggedIn = computed(() => Boolean(sessionToken()));
const maskedUserId = computed(() => maskUserId(userId.value || String(uni.getStorageSync("shuxin_user_id") || "")));

onShow(() => {
  loadProfile();
});

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
          reject(new Error(res.data?.error || `请求失败: ${res.statusCode}`));
        }
      },
      fail: (error) => reject(new Error(error.errMsg || "请求失败"))
    });
  });
}

async function loadProfile() {
  const token = sessionToken();
  if (!token) {
    uni.redirectTo({ url: "/pages/login/login" });
    return;
  }
  loading.value = true;
  message.value = "";
  try {
    const result = await request("/api/devices/my", { session_token: token });
    userId.value = result.user_id || String(uni.getStorageSync("shuxin_user_id") || "");
    deviceCount.value = (result.items || []).length;
  } catch (error) {
    message.value = error.message || String(error);
  } finally {
    loading.value = false;
  }
}

function logout() {
  uni.removeStorageSync("shuxin_session_token");
  uni.removeStorageSync("shuxin_session_expires_at");
  uni.removeStorageSync("shuxin_user_id");
  uni.redirectTo({ url: "/pages/login/login" });
}

function maskUserId(value: string): string {
  if (!value) return "未登录";
  if (value.length <= 12) return value;
  return `${value.slice(0, 6)}...${value.slice(-4)}`;
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 48rpx 34rpx 64rpx;
  background:
    radial-gradient(circle at 82% 0%, rgba(224, 114, 83, 0.16), transparent 34%),
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

.panel {
  padding: 28rpx;
  background: rgba(255, 252, 246, 0.92);
  border: 1rpx solid rgba(128, 94, 69, 0.16);
  border-radius: 24rpx;
  box-shadow: 0 18rpx 50rpx rgba(70, 48, 32, 0.08);
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20rpx;
  padding: 22rpx 0;
  border-bottom: 1rpx solid rgba(128, 94, 69, 0.12);
}

.label {
  color: #82786d;
  font-size: 24rpx;
}

.value {
  color: #25211c;
  font-size: 32rpx;
  font-weight: 700;
  margin-top: 8rpx;
}

.mini,
.danger {
  height: 68rpx;
  line-height: 68rpx;
  font-size: 24rpx;
}

.mini {
  flex: 0 0 132rpx;
  color: #2f604f;
  background: #e4eee8;
}

.danger {
  width: 100%;
  margin-top: 28rpx;
  color: #9e3b35;
  background: #f3ded9;
}

.message {
  margin-top: 20rpx;
  color: #9e3b35;
  font-size: 26rpx;
}
</style>
