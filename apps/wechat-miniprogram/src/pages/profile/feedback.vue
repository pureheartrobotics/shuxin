<template>
  <view class="page">
    <view class="hero">
      <view class="eyebrow">FEEDBACK</view>
      <view class="title">意见反馈</view>
      <view class="subtitle">您的声音对我们至关重要，请告诉我们您的想法或遇到的问题。</view>
    </view>

    <view class="panel">
      <view class="form-group">
        <view class="label">反馈内容</view>
        <textarea
          class="textarea"
          v-model="content"
          placeholder="请详细描述您遇到的问题或宝贵的建议，以便我们能更好地为您服务..."
          maxlength="500"
        />
        <view class="word-count">{{ content.length }}/500</view>
      </view>

      <view class="form-group">
        <view class="label">联系方式 (可选)</view>
        <input
          class="input"
          v-model="contact"
          placeholder="请留下您的手机号、微信号或邮箱，方便我们与您联系..."
          maxlength="100"
        />
      </view>

      <view v-if="message" class="message" :class="resultKind">{{ message }}</view>

      <button class="primary" :disabled="loading || !content.trim()" @tap="submitFeedback">
        {{ loading ? "提交中..." : "提交反馈" }}
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";

const apiBase = import.meta.env.VITE_SHUXIN_API_BASE || "http://localhost:8765";
const content = ref("");
const contact = ref("");
const loading = ref(false);
const message = ref("");
const resultKind = ref<"success" | "error" | "info">("info");

function sessionToken(): string {
  const token = String(uni.getStorageSync("shuxin_session_token") || "");
  const expiresAt = String(uni.getStorageSync("shuxin_session_expires_at") || "");
  if (!token) return "";
  if (expiresAt && Date.parse(expiresAt) <= Date.now()) return "";
  return token;
}

function setMessage(kind: "success" | "error" | "info", text: string) {
  resultKind.value = kind;
  message.value = text;
}

async function submitFeedback() {
  if (!content.value.trim()) {
    setMessage("error", "请先输入反馈内容");
    return;
  }

  const token = sessionToken();
  if (!token) {
    uni.redirectTo({ url: "/pages/login/login" });
    return;
  }

  loading.value = true;
  setMessage("info", "");

  try {
    const response: any = await new Promise((resolve, reject) => {
      uni.request({
        url: `${apiBase}/api/feedbacks`,
        method: "POST",
        data: {
          session_token: token,
          content: content.value.trim(),
          contact: contact.value.trim()
        },
        success: (res) => {
          if (res.statusCode >= 200 && res.statusCode < 300 && !res.data?.error) {
            resolve(res.data);
          } else {
            reject(new Error(res.data?.error || `提交失败: ${res.statusCode}`));
          }
        },
        fail: (error) => reject(new Error(error.errMsg || "网络请求失败"))
      });
    });

    if (response.ok) {
      setMessage("success", "感谢您的宝贵意见！反馈提交成功，正在返回...");
      content.value = "";
      contact.value = "";
      setTimeout(() => {
        uni.navigateBack();
      }, 2000);
    } else {
      setMessage("error", "提交反馈失败，请稍后重试");
    }
  } catch (error: any) {
    setMessage("error", error.message || "提交反馈失败，请检查网络连接");
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: #f7f4ee;
  padding: 42rpx 32rpx;
  box-sizing: border-box;
}

.hero {
  padding: 24rpx 4rpx 48rpx;
}

.eyebrow {
  color: #2f604f;
  font-size: 20rpx;
  font-weight: 700;
  letter-spacing: 2rpx;
}

.title {
  color: #25211c;
  font-size: 48rpx;
  font-weight: 700;
  margin-top: 10rpx;
}

.subtitle {
  color: #82786d;
  font-size: 26rpx;
  line-height: 1.5;
  margin-top: 14rpx;
}

.panel {
  background: #fffaf3;
  border-radius: 28rpx;
  padding: 42rpx 36rpx;
  box-shadow: 0 8rpx 30rpx rgba(70, 48, 32, 0.06);
  border: 1rpx solid rgba(128, 94, 69, 0.1);
}

.form-group {
  margin-bottom: 36rpx;
  position: relative;
}

.label {
  color: #82786d;
  font-size: 24rpx;
  font-weight: 600;
  margin-bottom: 14rpx;
}

.textarea {
  width: 100%;
  height: 280rpx;
  background: #ffffff;
  border-radius: 18rpx;
  padding: 24rpx;
  font-size: 28rpx;
  color: #25211c;
  box-sizing: border-box;
  border: 1rpx solid rgba(128, 94, 69, 0.14);
}

.word-count {
  position: absolute;
  bottom: 16rpx;
  right: 24rpx;
  font-size: 22rpx;
  color: #a59b90;
}

.input {
  width: 100%;
  height: 88rpx;
  background: #ffffff;
  border-radius: 18rpx;
  padding: 0 24rpx;
  font-size: 28rpx;
  color: #25211c;
  box-sizing: border-box;
  border: 1rpx solid rgba(128, 94, 69, 0.14);
}

.message {
  margin: 10rpx 0 24rpx;
  font-size: 26rpx;
  line-height: 1.4;
}

.message.info {
  color: #82786d;
}

.message.success {
  color: #2f604f;
}

.message.error {
  color: #9e3b35;
}

button {
  width: 100%;
  height: 88rpx;
  line-height: 88rpx;
  border-radius: 20rpx;
  font-size: 28rpx;
  font-weight: 600;
  margin-top: 24rpx;
}

.primary {
  color: #fff;
  background: #2f604f;
  box-shadow: 0 6rpx 16rpx rgba(47, 96, 79, 0.2);
}

.primary[disabled] {
  background: #8eaba0;
  color: rgba(255, 255, 255, 0.7);
  box-shadow: none;
}
</style>
