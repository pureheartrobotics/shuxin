<template>
  <view class="page">
    <view class="hero">
      <view class="eyebrow">CHUXIN ACCOUNT</view>
      <view class="title">个人中心</view>
      <view class="subtitle">{{ loggedIn ? "微信身份已登录" : "尚未登录" }}</view>
    </view>

    <!-- 资料分组：微信式 cell；头像直达 chooseAvatar（官方推荐） -->
    <view class="panel profile-panel">
      <view class="cell avatar-cell">
        <text class="cell-label">头像</text>
        <view class="cell-right">
          <button
            class="avatar-hit"
            open-type="chooseAvatar"
            :disabled="saving"
            hover-class="none"
            @chooseavatar="onChooseAvatar"
          >
            <image
              v-if="avatarUrl"
              class="avatar"
              :src="avatarUrl"
              mode="aspectFill"
            />
            <view v-else class="avatar avatar-placeholder">{{ displayName.slice(0, 1) }}</view>
          </button>
          <view class="cell-more" @tap.stop="showAvatarMenu">
            <text class="chev">›</text>
          </view>
        </view>
      </view>
      <view class="cell nick-cell">
        <text class="cell-label">昵称</text>
        <input
          class="cell-input"
          type="nickname"
          maxlength="32"
          :disabled="saving"
          :value="nickname"
          placeholder="点此填写，可选用微信昵称"
          placeholder-class="cell-placeholder"
          @input="onNicknameInput"
          @change="onNicknameChange"
          @blur="onNicknameBlur"
        />
      </view>
      <view class="cell-hint">点头像用微信头像；点 › 可从相册选择或恢复默认。昵称：聚焦后在键盘上方点选微信昵称，也可自行输入</view>
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
          <view class="label">账户剩余陪伴点</view>
          <view class="value" :class="{ exhausted: quotaExhausted }">{{ balanceLabel }}</view>
          <view v-if="quotaExhausted" class="hint">陪伴点已用尽，请充值后继续使用</view>
        </view>
        <button class="mini recharge" :disabled="loading || paying" @tap="openPaymentSheet">充值</button>
      </view>
      <view class="row legal-row">
        <view>
          <view class="label">法律条款</view>
          <view class="legal-links">
            <text class="legal-link" @tap="openTerms">用户服务协议</text>
            <text class="legal-sep">·</text>
            <text class="legal-link" @tap="openPrivacy">隐私政策</text>
          </view>
        </view>
      </view>
      <view class="row">
        <view>
          <view class="label">商城订单</view>
          <view class="value" style="font-weight: normal; font-size: 26rpx; color: #82786d; margin-top: 6rpx;">查看实体商品购买记录</view>
        </view>
        <button class="mini" @tap="openMallOrders">查看</button>
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
        <view class="sheet-subtitle">支付成功后自动增加账户剩余陪伴点</view>
        <view v-if="plansLoading" class="sheet-hint">加载套餐中...</view>
        <view v-else-if="!plans.length" class="sheet-hint">暂无可用套餐</view>
        <view v-else class="plan-list">
          <view
            v-for="plan in plans"
            :key="plan.id"
            class="plan-card"
            @tap="handlePurchasePlan(plan)"
          >
            <view>
              <view class="plan-name">{{ plan.name }}</view>
              <view class="plan-desc">{{ planDisplayDesc(plan) }}</view>
            </view>
            <view class="plan-price">¥{{ plan.amount_yuan }}</view>
          </view>
        </view>
        <button class="sheet-close" :disabled="paying" @tap="closePaymentSheet">取消</button>
      </view>
    </view>

    <!-- › 菜单：相册 / 恢复（微信头像由头像按钮直达） -->
    <view v-if="avatarMenuVisible" class="sheet-mask" @tap="closeAvatarMenu">
      <view class="sheet avatar-sheet" @tap.stop>
        <view class="sheet-title">更换头像</view>
        <button class="avatar-menu-btn" :disabled="saving" hover-class="none" @tap="pickFromAlbum">
          从相册选择
        </button>
        <button
          v-if="hasCustomAvatar"
          class="avatar-menu-btn"
          :disabled="saving"
          hover-class="none"
          @tap="restoreDefaultAvatar"
        >
          恢复默认
        </button>
        <button class="sheet-close" :disabled="saving" @tap="closeAvatarMenu">取消</button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { onShow } from "@dcloudio/uni-app";
import { computed } from "vue";
import { isLoggedIn } from "../../core/auth";
import { useProfile } from "../../modules/account/composables/useProfile";
import { useQuotaPayment } from "../../modules/account/composables/useQuotaPayment";
import type { PaymentPlan } from "../../modules/account/api/payment-quota";
import { describePlanForUser } from "../../utils/companion-points";

const profile = useProfile();
const quotaPayment = useQuotaPayment();

const {
  loading,
  saving,
  factoryQa,
  quotaExhausted,
  loggedIn,
  displayUserId,
  displayName,
  balanceLabel,
  nickname,
  avatarUrl,
  hasCustomAvatar,
  avatarMenuVisible,
  loadProfile,
  onNicknameInput,
  onNicknameBlur,
  onNicknameChange,
  onChooseAvatar,
  pickFromAlbum,
  restoreDefaultAvatar,
  showAvatarMenu,
  closeAvatarMenu,
  logout,
  copyUserId,
} = profile;

const {
  paying,
  plansLoading,
  showPaymentSheet,
  plans,
  openPaymentSheet,
  closePaymentSheet,
  purchasePlan,
} = quotaPayment;

const message = computed(() => quotaPayment.message.value || profile.message.value);

function planDisplayDesc(plan: PaymentPlan) {
  return (
    describePlanForUser(plan.description, plan.duration_minutes) ||
    (plan.duration_days ? `${plan.duration_days} 天订阅` : "充值套餐")
  );
}

onShow(() => {
  if (!isLoggedIn()) {
    uni.redirectTo({ url: "/pages/login/login" });
    return;
  }
  loadProfile();
});

function navigateToFeedback() {
  uni.navigateTo({ url: "/pages/profile/feedback" });
}

function openTerms() {
  uni.navigateTo({ url: "/pages/legal/terms" });
}

function openPrivacy() {
  uni.navigateTo({ url: "/pages/legal/privacy" });
}

function openMallOrders() {
  uni.navigateTo({ url: "/modules/mall/pages/order/list" });
}

function openFactoryVerify() {
  uni.navigateTo({ url: "/pages/factory/verify" });
}

async function handlePurchasePlan(plan: Parameters<typeof purchasePlan>[0]) {
  await purchasePlan(plan, loadProfile);
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
  margin-bottom: 24rpx;
}

.profile-panel {
  padding: 8rpx 28rpx 20rpx;
}

.cell {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 104rpx;
  padding: 12rpx 0;
  border-bottom: 1rpx solid rgba(128, 94, 69, 0.12);
}

.cell:last-of-type {
  border-bottom: none;
}

.cell-label {
  flex: 0 0 auto;
  color: #25211c;
  font-size: 28rpx;
  font-weight: 500;
}

.cell-right {
  display: flex;
  align-items: center;
  gap: 8rpx;
}

.avatar-hit {
  margin: 0;
  padding: 0;
  width: 96rpx;
  height: 96rpx;
  border-radius: 48rpx;
  background: transparent;
  line-height: 1;
  overflow: hidden;
}

.avatar-hit::after {
  border: none;
}

.avatar {
  width: 96rpx;
  height: 96rpx;
  border-radius: 48rpx;
  background: #e4eee8;
  display: block;
}

.avatar-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #2f604f;
  font-size: 36rpx;
  font-weight: 700;
}

.cell-more {
  padding: 16rpx 4rpx 16rpx 12rpx;
}

.chev {
  color: #b0a89e;
  font-size: 40rpx;
  line-height: 1;
}

.cell-input {
  flex: 1;
  margin-left: 24rpx;
  text-align: right;
  font-size: 28rpx;
  color: #25211c;
  height: 64rpx;
  line-height: 64rpx;
}

.cell-placeholder {
  color: #b5aa9d;
}

.cell-hint {
  padding: 4rpx 0 8rpx;
  color: #9a9186;
  font-size: 22rpx;
  line-height: 1.4;
}

.avatar-sheet {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.avatar-menu-btn {
  margin: 0;
  width: 100%;
  height: 96rpx;
  line-height: 96rpx;
  font-size: 30rpx;
  color: #25211c;
  background: #f5efe6;
  border-radius: 20rpx;
}

.avatar-menu-btn::after {
  border: none;
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

.legal-row {
  align-items: flex-start;
}

.legal-links {
  margin-top: 10rpx;
  font-size: 26rpx;
  line-height: 1.6;
}

.legal-link {
  color: #2f604f;
  font-weight: 600;
}

.legal-sep {
  color: #b5aa9d;
  margin: 0 10rpx;
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
