<template>
  <view class="page">
    <view class="brand">
      <view class="eyebrow">CHUXIN DEVICE</view>
      <view class="title">登录后绑定设备</view>
      <view class="subtitle">使用微信身份确认设备归属，再扫描机器人外壳认领码完成绑定。</view>
    </view>

    <view class="panel">
      <view class="step">
        <view class="step-index">1</view>
        <view>
          <view class="step-title">微信身份</view>
          <view class="step-text">仅用于生成当前微信用户的设备绑定关系。</view>
        </view>
      </view>
      <view class="step">
        <view class="step-index">2</view>
        <view>
          <view class="step-title">扫码绑定</view>
          <view class="step-text">外壳条形码只包含认领码，不包含设备密钥。</view>
        </view>
      </view>
      <button class="primary" :disabled="loading" @tap="loginAndContinue">进入设备绑定</button>
      <view class="policy">继续表示你已阅读并同意用户协议与隐私说明。</view>
      <view v-if="message" class="message">{{ message }}</view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";

const apiBase = import.meta.env.VITE_SHUXIN_API_BASE || "http://localhost:8765";
const loading = ref(false);
const message = ref("");

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

function loginAndContinue() {
  loading.value = true;
  message.value = "";
  uni.login({
    provider: "weixin",
    success: async (res) => {
      const code = res.code || "";
      if (!code) {
        message.value = "微信登录失败，请稍后重试";
        loading.value = false;
        return;
      }
      try {
        const session = await request("/api/wechat/login", { wx_code: code });
        uni.setStorageSync("shuxin_session_token", session.session_token || "");
        uni.setStorageSync("shuxin_session_expires_at", session.expires_at || "");
        uni.setStorageSync("shuxin_user_id", session.user_id || "");
        uni.switchTab({ url: "/pages/index/index" });
      } catch (error) {
        message.value = error.message || String(error);
      } finally {
        loading.value = false;
      }
    },
    fail: (error) => {
      message.value = error.errMsg || "微信登录失败";
      loading.value = false;
    }
  });
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 56rpx 34rpx 72rpx;
  background:
    radial-gradient(circle at 82% 4%, rgba(47, 96, 79, 0.18), transparent 32%),
    linear-gradient(180deg, #f8f1e7 0%, #f3eee7 52%, #ece7df 100%);
}

.brand {
  padding: 42rpx 4rpx 50rpx;
}

.eyebrow {
  color: #9b6146;
  font-size: 22rpx;
  letter-spacing: 2rpx;
  margin-bottom: 14rpx;
}

.title {
  color: #24211c;
  font-size: 58rpx;
  font-weight: 700;
  line-height: 1.12;
}

.subtitle {
  color: #6f665b;
  font-size: 28rpx;
  line-height: 1.65;
  margin-top: 20rpx;
}

.panel {
  padding: 30rpx;
  background: rgba(255, 252, 246, 0.94);
  border: 1rpx solid rgba(128, 94, 69, 0.16);
  border-radius: 24rpx;
  box-shadow: 0 18rpx 50rpx rgba(70, 48, 32, 0.08);
}

.step {
  display: flex;
  gap: 20rpx;
  padding: 18rpx 0;
}

.step-index {
  flex: 0 0 48rpx;
  height: 48rpx;
  line-height: 48rpx;
  text-align: center;
  color: #fff;
  background: #2f604f;
  border-radius: 50%;
  font-size: 24rpx;
}

.step-title {
  color: #25211c;
  font-size: 30rpx;
  font-weight: 700;
}

.step-text,
.policy {
  color: #82786d;
  font-size: 24rpx;
  line-height: 1.5;
  margin-top: 6rpx;
}

.primary {
  width: 100%;
  height: 88rpx;
  line-height: 88rpx;
  margin-top: 28rpx;
  color: #fff;
  background: #2f604f;
  border-radius: 18rpx;
  font-size: 28rpx;
}

.policy {
  text-align: center;
  margin-top: 18rpx;
}

.message {
  margin-top: 18rpx;
  color: #9e3b35;
  font-size: 26rpx;
}
</style>
