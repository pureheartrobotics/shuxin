<template>
  <view class="page">
    <view class="brand">
      <view class="eyebrow">CHUXIN</view>
      <view class="title">登录后开始陪伴</view>
      <view class="subtitle">使用微信身份登录，抽卡遇见伙伴，文字与语音都能聊。</view>
    </view>

    <view class="panel">
      <view class="step">
        <view class="step-index">1</view>
        <view>
          <view class="step-title">微信登录</view>
          <view class="step-text">确认你的账号，同步额度与伙伴列表。</view>
        </view>
      </view>
      <view class="step">
        <view class="step-index">2</view>
        <view>
          <view class="step-title">抽卡与聊天</view>
          <view class="step-text">免费抽卡获得性格伙伴，随时回来聊聊。</view>
        </view>
      </view>
      <view class="policy-row">
        <checkbox-group @change="onPolicyChange">
          <label class="policy-label">
            <checkbox
              value="agreed"
              :checked="policyAgreed"
              color="#2f604f"
            />
            <view class="policy-text">
              <text>我已阅读并同意</text>
              <text class="policy-link" @tap.stop="openTerms">《用户服务协议》</text>
              <text>和</text>
              <text class="policy-link" @tap.stop="openPrivacy">《隐私政策》</text>
            </view>
          </label>
        </checkbox-group>
      </view>
      <button class="primary" :disabled="loading || !policyAgreed" @tap="loginAndContinue">进入伙伴</button>
      <view v-if="message" class="message">{{ message }}</view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { isPolicyAgreed, markPolicyAgreed } from "../../utils/policy";

const apiBase = import.meta.env.VITE_SHUXIN_API_BASE || "http://localhost:8765";
const loading = ref(false);
const message = ref("");
const policyAgreed = ref(false);

onMounted(() => {
  policyAgreed.value = isPolicyAgreed();
});

function onPolicyChange(event: { detail: { value: string[] } }) {
  policyAgreed.value = event.detail.value.includes("agreed");
}

function openTerms() {
  uni.navigateTo({ url: "/pages/legal/terms" });
}

function openPrivacy() {
  uni.navigateTo({ url: "/pages/legal/privacy" });
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

function loginAndContinue() {
  if (!policyAgreed.value) {
    uni.showToast({ title: "请先阅读并同意相关协议", icon: "none" });
    return;
  }
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
        markPolicyAgreed();
        uni.setStorageSync("shuxin_session_token", session.session_token || "");
        uni.setStorageSync("shuxin_session_expires_at", session.expires_at || "");
        uni.setStorageSync("shuxin_user_id", session.user_id || "");
        uni.switchTab({ url: "/pages/partners/partners" });
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

.step-text {
  color: #82786d;
  font-size: 24rpx;
  line-height: 1.5;
  margin-top: 6rpx;
}

.policy-row {
  margin-top: 24rpx;
}

.policy-label {
  display: flex;
  align-items: flex-start;
  gap: 12rpx;
}

.policy-text {
  flex: 1;
  color: #82786d;
  font-size: 24rpx;
  line-height: 1.65;
}

.policy-link {
  color: #2f604f;
  font-weight: 600;
}

.primary {
  width: 100%;
  height: 88rpx;
  line-height: 88rpx;
  margin-top: 20rpx;
  color: #fff;
  background: #2f604f;
  border-radius: 18rpx;
  font-size: 28rpx;
}

.primary[disabled] {
  color: rgba(255, 255, 255, 0.72);
  background: #8aa89c;
}

.message {
  margin-top: 18rpx;
  color: #9e3b35;
  font-size: 26rpx;
}
</style>
