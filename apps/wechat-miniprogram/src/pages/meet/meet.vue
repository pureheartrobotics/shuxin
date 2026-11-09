<template>
  <view class="stage">
    <view class="field">
      <view class="glow glow-a" />
      <view class="glow glow-b" />
      <view class="ring ring-outer" />
      <view class="ring ring-mid" />
      <view class="ring ring-inner" />
      <view class="core" />
      <view class="scan" />
      <view class="corner corner-tl" />
      <view class="corner corner-tr" />
      <view class="corner corner-bl" />
      <view class="corner corner-br" />
    </view>

    <view class="hud">
      <text class="hud-mark">初次见面</text>
      <view class="meters">
        <view class="meter" :class="{ on: beat >= 1 }" />
        <view class="meter" :class="{ on: beat >= 2 }" />
        <view class="meter" :class="{ on: beat >= 3 }" />
      </view>
    </view>

    <view v-if="beat === 1" class="beat" @tap="completeGreeting">
      <text class="hello">你好，人类，</text>
      <text class="hello hello-next">我是你的朋友初心。</text>
      <text class="whisper">轻触，继续听我说</text>
    </view>

    <view v-else-if="beat === 2" class="beat" @tap="completeIntro">
      <text class="eyebrow">机器人代号</text>
      <text class="designation">{{ designation }}</text>
      <text class="intro">我是初心。机器人代号 {{ designation }}。这次扫描把我交到你面前，往后这一台，只认你。</text>
      <text class="whisper">轻触，告诉我你是谁</text>
    </view>

    <view v-else-if="beat === 3" class="beat beat-ask">
      <text class="eyebrow">称呼</text>
      <text class="ask">你希望我怎么称呼你？</text>
      <text class="intro ask-note">一个名字。{{ designation }} 只以此记住你。</text>
      <input
        class="name-input"
        type="text"
        v-model="userName"
        maxlength="16"
        confirm-type="done"
        placeholder="你的名字"
        placeholder-class="name-placeholder"
        :focus="nameFocus"
        @confirm="finishMeet"
      />
      <view class="commit" hover-class="commit-on" @tap="finishMeet">就这么约定</view>
    </view>

    <view v-if="closing" class="closing">
      <text class="closing-line">{{ closingLine }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { onLoad } from "@dcloudio/uni-app";
import { nextTick, ref } from "vue";
import {
  captureEnterOptions,
  captureLaunchQuery,
  completeFirstMeet,
  isFirstMeetComplete,
  resolveDesignation,
} from "../../core/first-meet";

const beat = ref(0);
const designation = ref("");
const userName = ref("");
const nameFocus = ref(false);
const locked = ref(false);
const closing = ref(false);
const closingLine = ref("");

onLoad((query) => {
  captureLaunchQuery(query as Record<string, unknown> | undefined);
  captureEnterOptions();
  if (isFirstMeetComplete()) {
    uni.switchTab({ url: "/pages/index/index" });
    return;
  }
  designation.value = resolveDesignation();
  beat.value = 1;
});

function arm(next: number) {
  if (locked.value) return;
  locked.value = true;
  beat.value = next;
  setTimeout(() => {
    locked.value = false;
  }, 720);
}

function completeGreeting() {
  if (beat.value !== 1) return;
  designation.value = resolveDesignation();
  arm(2);
}

function completeIntro() {
  if (beat.value !== 2) return;
  arm(3);
  nextTick(() => {
    nameFocus.value = true;
  });
}

function finishMeet() {
  if (beat.value !== 3 || locked.value || closing.value) return;
  const name = userName.value.trim();
  if (!name) {
    uni.showToast({ title: "先留下你的名字", icon: "none" });
    return;
  }
  locked.value = true;
  const code = resolveDesignation();
  designation.value = code;
  completeFirstMeet(name, code);
  closingLine.value = `${name}，我记住了。`;
  closing.value = true;
  setTimeout(() => {
    uni.switchTab({ url: "/pages/index/index" });
  }, 520);
}
</script>

<style scoped>
.stage {
  position: relative;
  min-height: 100vh;
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
}

.glow {
  position: absolute;
  border-radius: 50%;
}

.glow-a {
  top: -80rpx;
  left: -120rpx;
  width: 520rpx;
  height: 520rpx;
  background: radial-gradient(circle, rgba(120, 255, 226, 0.22) 0%, rgba(120, 255, 226, 0) 68%);
}

.glow-b {
  right: -160rpx;
  bottom: 40rpx;
  width: 460rpx;
  height: 460rpx;
  background: radial-gradient(circle, rgba(240, 196, 154, 0.16) 0%, rgba(240, 196, 154, 0) 70%);
}

.ring {
  position: absolute;
  left: 50%;
  top: 46%;
  border-radius: 50%;
  border: 1rpx solid rgba(141, 255, 232, 0.28);
}

.ring-outer {
  width: 640rpx;
  height: 640rpx;
  margin-left: -320rpx;
  margin-top: -320rpx;
  border-style: dashed;
  animation: spin 36s linear infinite;
}

.ring-mid {
  width: 460rpx;
  height: 460rpx;
  margin-left: -230rpx;
  margin-top: -230rpx;
  border-color: rgba(141, 255, 232, 0.45);
  animation: spin-back 22s linear infinite;
}

.ring-inner {
  width: 280rpx;
  height: 280rpx;
  margin-left: -140rpx;
  margin-top: -140rpx;
  box-shadow: 0 0 24rpx rgba(141, 255, 232, 0.18);
  animation: spin 18s linear infinite;
}

.core {
  position: absolute;
  left: 50%;
  top: 46%;
  width: 14rpx;
  height: 14rpx;
  margin-left: -7rpx;
  margin-top: -7rpx;
  border-radius: 50%;
  background: #f2d2b0;
  box-shadow:
    0 0 16rpx 6rpx rgba(242, 210, 176, 0.9),
    0 0 70rpx 18rpx rgba(120, 255, 226, 0.28);
  animation: pulse 2.8s ease-in-out infinite;
}

.scan {
  position: absolute;
  left: 8%;
  right: 8%;
  height: 2rpx;
  background: linear-gradient(90deg, rgba(141, 255, 232, 0), rgba(141, 255, 232, 0.9), rgba(141, 255, 232, 0));
  box-shadow: 0 0 16rpx rgba(141, 255, 232, 0.65);
  animation: scan 5.2s ease-in-out infinite;
}

.corner {
  position: absolute;
  width: 36rpx;
  height: 36rpx;
  border-color: rgba(141, 255, 232, 0.7);
  border-style: solid;
}

.corner-tl {
  top: 28rpx;
  left: 28rpx;
  border-width: 2rpx 0 0 2rpx;
}

.corner-tr {
  top: 28rpx;
  right: 28rpx;
  border-width: 2rpx 2rpx 0 0;
}

.corner-bl {
  bottom: 28rpx;
  left: 28rpx;
  border-width: 0 0 2rpx 2rpx;
}

.corner-br {
  right: 28rpx;
  bottom: 28rpx;
  border-width: 0 2rpx 2rpx 0;
}

.hud {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 88rpx 48rpx 0;
}

.hud-mark {
  color: rgba(196, 228, 220, 0.72);
  font-size: 22rpx;
  letter-spacing: 6rpx;
}

.meters {
  display: flex;
}

.meter {
  width: 36rpx;
  height: 2rpx;
  margin-left: 10rpx;
  background: rgba(141, 255, 232, 0.2);
}

.meter.on {
  background: #8dffe8;
  box-shadow: 0 0 8rpx rgba(141, 255, 232, 0.8);
}

.beat {
  position: relative;
  z-index: 2;
  min-height: 68vh;
  padding: 18vh 64rpx 0;
  animation: arrive 0.72s ease both;
}

.hello {
  display: block;
  color: #f7fffc;
  font-size: 64rpx;
  font-weight: 500;
  line-height: 1.35;
  text-shadow: 0 0 28rpx rgba(141, 255, 232, 0.35);
}

.hello-next {
  margin-top: 8rpx;
}

.eyebrow {
  display: block;
  color: #8dffe8;
  font-size: 24rpx;
  letter-spacing: 8rpx;
}

.designation {
  display: block;
  margin-top: 28rpx;
  color: #f4fffb;
  font-size: 92rpx;
  font-weight: 600;
  letter-spacing: 8rpx;
  line-height: 1.1;
  text-shadow:
    0 0 18rpx rgba(141, 255, 232, 0.85),
    0 0 48rpx rgba(141, 255, 232, 0.35);
}

.intro,
.ask-note {
  display: block;
  width: 600rpx;
  margin-top: 36rpx;
  color: rgba(214, 232, 228, 0.82);
  font-size: 30rpx;
  line-height: 1.7;
}

.ask {
  display: block;
  margin-top: 22rpx;
  color: #f7fffc;
  font-size: 56rpx;
  font-weight: 500;
  line-height: 1.35;
  text-shadow: 0 0 24rpx rgba(141, 255, 232, 0.28);
}

.ask-note {
  margin-top: 20rpx;
}

.whisper {
  display: block;
  margin-top: 72rpx;
  color: rgba(141, 255, 232, 0.72);
  font-size: 24rpx;
  letter-spacing: 4rpx;
}

.beat-ask {
  padding-top: 12vh;
}

.name-input {
  width: 100%;
  height: 96rpx;
  margin-top: 48rpx;
  padding: 0;
  border-bottom: 1rpx solid rgba(141, 255, 232, 0.55);
  background: transparent;
  color: #f7fffc;
  font-size: 44rpx;
}

.commit {
  width: 280rpx;
  height: 80rpx;
  margin-top: 56rpx;
  border: 1rpx solid rgba(141, 255, 232, 0.7);
  border-radius: 999rpx;
  color: #dffdf6;
  font-size: 28rpx;
  line-height: 80rpx;
  text-align: center;
  letter-spacing: 4rpx;
  box-shadow: 0 0 24rpx rgba(141, 255, 232, 0.16);
}

.commit-on {
  background: rgba(141, 255, 232, 0.12);
}

.closing {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 4;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(4, 6, 12, 0.72);
  animation: arrive 0.35s ease both;
}

.closing-line {
  color: #f7fffc;
  font-size: 48rpx;
  letter-spacing: 2rpx;
  text-shadow: 0 0 24rpx rgba(141, 255, 232, 0.45);
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes spin-back {
  from { transform: rotate(360deg); }
  to { transform: rotate(0deg); }
}

@keyframes pulse {
  0%, 100% { opacity: 0.72; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.35); }
}

@keyframes scan {
  0% { top: 16%; opacity: 0; }
  14% { opacity: 1; }
  86% { opacity: 1; }
  100% { top: 82%; opacity: 0; }
}

@keyframes arrive {
  from { opacity: 0; transform: translateY(28rpx); }
  to { opacity: 1; transform: translateY(0); }
}
</style>

<style>
page {
  background: #04060c;
  height: 100%;
}

.name-placeholder {
  color: rgba(180, 214, 208, 0.38);
}
</style>
