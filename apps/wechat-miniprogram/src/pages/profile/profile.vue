<template>
  <view class="page">
    <view class="hero">
      <view class="eyebrow">CHUXIN ACCOUNT</view>
      <view class="title">个人中心</view>
      <view class="subtitle">{{ loggedIn ? "微信身份已登录" : "尚未登录" }}</view>
    </view>

    <view class="panel">
      <view class="row user-id-row">
        <view class="user-id-block">
          <view class="label">当前用户</view>
          <view class="value user-id">{{ displayUserId }}</view>
        </view>
        <button class="mini copy" :disabled="!displayUserId || displayUserId === '未登录'" @tap="copyUserId">复制</button>
      </view>
      <view class="row">
        <view class="balance-block">
          <view class="label">账户剩余时长</view>
          <view class="value" :class="{ exhausted: quotaExhausted }">{{ balanceLabel }}</view>
          <view v-if="quotaExhausted" class="hint">额度已用尽，请充值后继续使用</view>
        </view>
        <button class="mini recharge" :disabled="loading || paying" @tap="openPaymentSheet">充值</button>
      </view>
      <view class="row">
        <view>
          <view class="label">绑定设备</view>
          <view class="value">{{ deviceCount }} 台</view>
        </view>
        <button class="mini" :disabled="loading" @tap="loadProfile">刷新</button>
      </view>
      <view class="row">
        <view>
          <view class="label">意见反馈</view>
          <view class="value" style="font-weight: normal; font-size: 26rpx; color: #82786d; margin-top: 6rpx;">提交您在使用中遇到的问题</view>
        </view>
        <button class="mini" @tap="navigateToFeedback">前往</button>
      </view>
      <button v-if="factoryQa" class="factory" @tap="openFactoryVerify">工厂验收</button>
      <button class="danger" @tap="logout">退出登录</button>
      <view v-if="message" class="message">{{ message }}</view>
    </view>

    <view v-if="showPaymentSheet" class="sheet-mask" @tap="closePaymentSheet">
      <view class="sheet" @tap.stop>
        <view class="sheet-title">选择购买套餐</view>
        <view class="sheet-subtitle">支付成功后自动增加到账户剩余时长</view>
        <view v-if="plansLoading" class="sheet-hint">加载套餐中...</view>
        <view v-else-if="!plans.length" class="sheet-hint">暂无可用套餐</view>
        <view v-else class="plan-list">
          <view
            v-for="plan in plans"
            :key="plan.id"
            class="plan-card"
            @tap="purchasePlan(plan)"
          >
            <view>
              <view class="plan-name">{{ plan.name }}</view>
              <view class="plan-desc">{{ plan.description || `${plan.duration_days} 天订阅` }}</view>
            </view>
            <view class="plan-price">¥{{ plan.amount_yuan }}</view>
          </view>
        </view>
        <button class="sheet-close" :disabled="paying" @tap="closePaymentSheet">取消</button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { onShow } from "@dcloudio/uni-app";
import { computed, ref } from "vue";

type PaymentPlan = {
  id: string;
  name: string;
  description?: string;
  amount_fen: number;
  amount_yuan: number;
  add_yuan: number;
  duration_days: number;
};

const apiBase = import.meta.env.VITE_SHUXIN_API_BASE || "http://localhost:8765";
const loading = ref(false);
const paying = ref(false);
const plansLoading = ref(false);
const message = ref("");
const userId = ref("");
const deviceCount = ref(0);
const factoryQa = ref(false);
const remainYuan = ref<number | null>(null);
const quotaConfigured = ref(false);
const quotaExhausted = ref(false);
const showPaymentSheet = ref(false);
const plans = ref<PaymentPlan[]>([]);
const loggedIn = computed(() => Boolean(sessionToken()));
const displayUserId = computed(() => userId.value || String(uni.getStorageSync("shuxin_user_id") || "") || "未登录");
const balanceLabel = computed(() => {
  if (!quotaConfigured.value) return "—";
  if (remainYuan.value == null) return "查询失败";
  return `${remainYuan.value} 分钟`;
});

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

function handleSessionError(errorMsg: string): boolean {
  if (errorMsg === "session_token is invalid or expired") {
    uni.removeStorageSync("shuxin_session_token");
    uni.removeStorageSync("shuxin_session_expires_at");
    uni.removeStorageSync("shuxin_user_id");
    uni.redirectTo({ url: "/pages/login/login" });
    return true;
  }
  return false;
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
          const errorMsg = res.data?.error || `请求失败: ${res.statusCode}`;
          handleSessionError(errorMsg);
          reject(new Error(errorMsg));
        }
      },
      fail: (error) => reject(new Error(error.errMsg || "请求失败"))
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
          const errorMsg = res.data?.error || `请求失败: ${res.statusCode}`;
          handleSessionError(errorMsg);
          reject(new Error(errorMsg));
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
    const [me, devices] = await Promise.all([
      request("/api/users/me", { session_token: token }),
      request("/api/devices/my", { session_token: token })
    ]);
    userId.value = me.user_id || String(uni.getStorageSync("shuxin_user_id") || "");
    factoryQa.value = Boolean(me.roles?.factory_qa);
    const quota = me.quota || {};
    deviceCount.value = (devices.items || []).length;
    quotaConfigured.value = Boolean(quota.configured);
    quotaExhausted.value = Boolean(quota.exhausted);
    remainYuan.value = quota.remain_yuan == null ? null : Number(quota.remain_yuan);
    if (quotaExhausted.value && quota.message) {
      message.value = quota.message;
    }
  } catch (error: any) {
    message.value = error.message || String(error);
  } finally {
    loading.value = false;
  }
}

function navigateToFeedback() {
  uni.navigateTo({ url: "/pages/profile/feedback" });
}

async function openPaymentSheet() {
  showPaymentSheet.value = true;
  plansLoading.value = true;
  message.value = "";
  try {
    const data = await requestGet("/api/payment/plans");
    plans.value = Array.isArray(data.items) ? data.items : [];
  } catch (error: any) {
    message.value = error.message || String(error);
    plans.value = [];
  } finally {
    plansLoading.value = false;
  }
}

function closePaymentSheet() {
  if (paying.value) return;
  showPaymentSheet.value = false;
}

async function purchasePlan(plan: PaymentPlan) {
  const token = sessionToken();
  if (!token) {
    uni.redirectTo({ url: "/pages/login/login" });
    return;
  }
  paying.value = true;
  message.value = "";
  try {
    const result = await request("/api/payment/create-order", {
      session_token: token,
      plan_id: plan.id
    });
    const params = result.pay_params || {};
    await new Promise<void>((resolve, reject) => {
      uni.requestPayment({
        provider: "wxpay",
        timeStamp: String(params.timeStamp || ""),
        nonceStr: String(params.nonceStr || ""),
        package: String(params.package || ""),
        signType: String(params.signType || "RSA"),
        paySign: String(params.paySign || ""),
        success: () => resolve(),
        fail: (error) => reject(new Error(error.errMsg || "支付失败"))
      });
    });
    message.value = "支付成功，额度更新中";
    showPaymentSheet.value = false;
    await loadProfile();
  } catch (error: any) {
    const text = error.message || String(error);
    if (!text.includes("cancel")) {
      message.value = text;
    }
  } finally {
    paying.value = false;
  }
}

function logout() {
  uni.removeStorageSync("shuxin_session_token");
  uni.removeStorageSync("shuxin_session_expires_at");
  uni.removeStorageSync("shuxin_user_id");
  uni.redirectTo({ url: "/pages/login/login" });
}

function copyUserId() {
  const value = displayUserId.value;
  if (!value || value === "未登录") return;
  uni.setClipboardData({
    data: value,
    success: () => uni.showToast({ title: "已复制", icon: "success" })
  });
}

function openFactoryVerify() {
  uni.navigateTo({ url: "/pages/factory/verify" });
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

.balance-block {
  flex: 1;
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

.value.exhausted {
  color: #9e3b35;
}

.user-id-row {
  align-items: flex-start;
}

.user-id-block {
  flex: 1;
  min-width: 0;
}

.user-id {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 24rpx;
  font-weight: 500;
  line-height: 1.5;
  word-break: break-all;
}

.mini.copy {
  flex: 0 0 120rpx;
  color: #4a5d52;
  background: #ece7df;
}

.factory {
  width: 100%;
  margin-top: 20rpx;
  color: #fffaf3;
  background: #6b4f3a;
}

.hint {
  color: #9e3b35;
  font-size: 24rpx;
  margin-top: 8rpx;
}

.mini,
.danger,
.sheet-close {
  height: 68rpx;
  line-height: 68rpx;
  font-size: 24rpx;
}

.mini {
  flex: 0 0 132rpx;
  color: #2f604f;
  background: #e4eee8;
}

.mini.recharge {
  color: #fffaf3;
  background: #2f604f;
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

.sheet-mask {
  position: fixed;
  inset: 0;
  background: rgba(36, 33, 28, 0.42);
  display: flex;
  align-items: flex-end;
  z-index: 20;
}

.sheet {
  width: 100%;
  padding: 36rpx 32rpx 48rpx;
  background: #fffaf3;
  border-radius: 28rpx 28rpx 0 0;
  box-shadow: 0 -12rpx 40rpx rgba(70, 48, 32, 0.12);
}

.sheet-title {
  color: #24211c;
  font-size: 36rpx;
  font-weight: 700;
}

.sheet-subtitle {
  color: #82786d;
  font-size: 24rpx;
  margin-top: 10rpx;
}

.sheet-hint {
  color: #82786d;
  font-size: 26rpx;
  padding: 36rpx 0;
}

.plan-list {
  margin-top: 24rpx;
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.plan-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24rpx 28rpx;
  border-radius: 20rpx;
  background: #f5efe6;
  border: 1rpx solid rgba(128, 94, 69, 0.14);
}

.plan-name {
  color: #24211c;
  font-size: 30rpx;
  font-weight: 700;
}

.plan-desc {
  color: #82786d;
  font-size: 22rpx;
  margin-top: 6rpx;
}

.plan-price {
  color: #2f604f;
  font-size: 34rpx;
  font-weight: 700;
}

.sheet-close {
  width: 100%;
  margin-top: 28rpx;
  color: #6f665b;
  background: #ece7df;
}
</style>
