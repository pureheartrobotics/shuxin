<template>
  <view v-if="visible" class="overlay" @tap.stop>
    <view class="card" @tap.stop>
      <view class="badge">{{ isFirstReveal ? "绑定成功" : "设备已绑定" }}</view>
      <view class="title">你的伙伴是 {{ mbti }} · {{ displayName }}</view>
      <view class="tagline">{{ tagline }}</view>
      <view v-if="isFirstReveal" class="hint">设备即将和你打招呼，会说明绑定成功与伙伴类型…</view>
      <view v-else class="hint">设备已完成绑定，首次开箱时才会语音自我介绍。</view>
      <view class="disclaimer">MBTI 为性格气质参考，非心理测评结果。</view>
      <button class="primary" @tap="onConfirm">知道了</button>
    </view>
  </view>
</template>

<script setup lang="ts">
defineProps<{
  visible: boolean;
  mbti: string;
  displayName: string;
  tagline: string;
  isFirstReveal: boolean;
}>();

const emit = defineEmits<{
  confirm: [];
}>();

function onConfirm() {
  emit("confirm");
}
</script>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48rpx;
  background: rgba(24, 20, 16, 0.58);
}

.card {
  width: 100%;
  max-width: 620rpx;
  padding: 44rpx 36rpx 36rpx;
  border-radius: 28rpx;
  background: linear-gradient(180deg, #fffdf8 0%, #f7f1e8 100%);
  box-shadow: 0 28rpx 80rpx rgba(36, 24, 12, 0.22);
}

.badge {
  display: inline-flex;
  padding: 8rpx 18rpx;
  border-radius: 999rpx;
  background: rgba(36, 88, 73, 0.12);
  color: #245849;
  font-size: 24rpx;
  font-weight: 600;
}

.title {
  margin-top: 28rpx;
  color: #24211c;
  font-size: 40rpx;
  font-weight: 700;
  line-height: 1.35;
}

.tagline {
  margin-top: 18rpx;
  color: #5f564c;
  font-size: 28rpx;
  line-height: 1.65;
}

.hint {
  margin-top: 22rpx;
  color: #9b6146;
  font-size: 24rpx;
}

.disclaimer {
  margin-top: 24rpx;
  color: #9a9288;
  font-size: 22rpx;
  line-height: 1.5;
}

.primary {
  margin-top: 34rpx;
  width: 100%;
  height: 88rpx;
  line-height: 88rpx;
  border-radius: 999rpx;
  background: #245849;
  color: #fff;
  font-size: 30rpx;
  font-weight: 600;
}
</style>
