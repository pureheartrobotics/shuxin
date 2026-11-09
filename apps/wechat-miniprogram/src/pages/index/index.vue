<template>
  <view class="page">
    <view class="field">
      <view class="glow glow-a" />
      <view class="glow glow-b" />
      <view class="ring ring-outer" />
      <view class="ring ring-mid" />
      <view class="corner corner-tl" />
      <view class="corner corner-tr" />
      <view class="corner corner-bl" />
      <view class="corner corner-br" />
    </view>

    <view v-if="ready" class="home">
      <text class="eyebrow">CHUXIN</text>
      <text class="relation">{{ userName }} · {{ designation }}</text>
      <view class="hairline" />
      <view class="facts">
        <view class="fact">
          <text class="label">称呼</text>
          <text class="value">{{ userName }}</text>
        </view>
        <view class="fact">
          <text class="label">机器人代号</text>
          <text class="value">{{ designation }}</text>
        </view>
      </view>
      <text class="oath">这一台，只认你。</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { onLoad, onShow } from "@dcloudio/uni-app";
import { ref } from "vue";
import {
  captureEnterOptions,
  captureLaunchQuery,
  isFirstMeetComplete,
  storedDesignation,
  storedUserName,
} from "../../core/first-meet";

const userName = ref("");
const designation = ref("");
const ready = ref(false);

function openBoundHome() {
  if (!isFirstMeetComplete()) {
    ready.value = false;
    uni.redirectTo({ url: "/pages/meet/meet" });
    return;
  }
  userName.value = storedUserName();
  designation.value = storedDesignation();
  ready.value = true;
}

onShow(() => {
  openBoundHome();
});

onLoad((query: Record<string, string | undefined>) => {
  captureLaunchQuery(query);
  captureEnterOptions();
  openBoundHome();
});
</script>

<style scoped>
.page {
  position: relative;
  min-height: 100vh;
  padding: 36rpx 34rpx 64rpx;
  overflow: hidden;
  background: #04060c;
  color: #f4fffb;
}

.field {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 0;
  pointer-events: none;
}

.glow {
  position: absolute;
  border-radius: 50%;
}

.glow-a {
  top: -120rpx;
  left: -80rpx;
  width: 480rpx;
  height: 480rpx;
  background: radial-gradient(circle, rgba(120, 255, 226, 0.2) 0%, rgba(120, 255, 226, 0) 68%);
}

.glow-b {
  right: -140rpx;
  bottom: 80rpx;
  width: 420rpx;
  height: 420rpx;
  background: radial-gradient(circle, rgba(240, 196, 154, 0.12) 0%, rgba(240, 196, 154, 0) 70%);
}

.ring {
  position: absolute;
  left: 78%;
  top: 22%;
  border-radius: 50%;
  border: 1rpx solid rgba(141, 255, 232, 0.22);
}

.ring-outer {
  width: 520rpx;
  height: 520rpx;
  margin-left: -260rpx;
  margin-top: -260rpx;
  border-style: dashed;
  animation: spin 36s linear infinite;
}

.ring-mid {
  width: 340rpx;
  height: 340rpx;
  margin-left: -170rpx;
  margin-top: -170rpx;
  animation: spin-back 24s linear infinite;
}

.corner {
  position: absolute;
  width: 28rpx;
  height: 28rpx;
  border-color: rgba(141, 255, 232, 0.55);
  border-style: solid;
}

.corner-tl {
  top: 12rpx;
  left: 12rpx;
  border-width: 2rpx 0 0 2rpx;
}

.corner-tr {
  top: 12rpx;
  right: 12rpx;
  border-width: 2rpx 2rpx 0 0;
}

.corner-bl {
  bottom: 12rpx;
  left: 12rpx;
  border-width: 0 0 2rpx 2rpx;
}

.corner-br {
  right: 12rpx;
  bottom: 12rpx;
  border-width: 0 2rpx 2rpx 0;
}

.home {
  position: relative;
  z-index: 1;
  padding: 28rpx 8rpx 0;
}

.eyebrow {
  display: block;
  color: #8dffe8;
  font-size: 22rpx;
  letter-spacing: 8rpx;
}

.relation {
  display: block;
  margin-top: 28rpx;
  color: #f7fffc;
  font-size: 64rpx;
  font-weight: 600;
  line-height: 1.2;
  letter-spacing: 2rpx;
  text-shadow:
    0 0 18rpx rgba(141, 255, 232, 0.55),
    0 0 42rpx rgba(141, 255, 232, 0.22);
}

.hairline {
  width: 120rpx;
  height: 1rpx;
  margin-top: 36rpx;
  background: rgba(141, 255, 232, 0.55);
  box-shadow: 0 0 12rpx rgba(141, 255, 232, 0.45);
}

.facts {
  margin-top: 48rpx;
  padding: 8rpx 28rpx;
  border: 1rpx solid rgba(141, 255, 232, 0.28);
  border-radius: 24rpx;
  background: rgba(6, 14, 20, 0.72);
  box-shadow: 0 0 28rpx rgba(141, 255, 232, 0.05);
}

.fact {
  padding: 28rpx 0;
  border-bottom: 1rpx solid rgba(141, 255, 232, 0.16);
}

.fact:last-child {
  border-bottom: none;
}

.label {
  display: block;
  color: #8dffe8;
  font-size: 22rpx;
  letter-spacing: 4rpx;
}

.value {
  display: block;
  margin-top: 12rpx;
  color: #f7fffc;
  font-size: 36rpx;
  font-weight: 500;
  letter-spacing: 2rpx;
}

.oath {
  display: block;
  margin-top: 48rpx;
  color: rgba(214, 232, 228, 0.72);
  font-size: 28rpx;
  letter-spacing: 4rpx;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes spin-back {
  from { transform: rotate(360deg); }
  to { transform: rotate(0deg); }
}
</style>

<style>
page {
  background: #04060c;
}
</style>
