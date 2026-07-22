<template>
  <view class="page">
    <view class="hero">
      <text class="title">我的伙伴</text>
      <text class="sub">免费抽卡养性格 · 文字与语音都能聊</text>
    </view>
    <view v-if="!items.length" class="empty">
      <text class="empty-text">还没有伙伴</text>
      <button class="primary" @click="goGacha">去抽卡</button>
    </view>
    <view v-else class="list">
      <view
        v-for="item in items"
        :key="item.companion_id"
        class="row"
        @click="openChat(item)"
      >
        <view class="avatar">{{ (item.mbti || '?').slice(0, 1) }}</view>
        <view class="meta">
          <text class="name">{{ item.display_name || item.mbti }}</text>
          <text class="mbti">{{ item.mbti }}</text>
        </view>
        <text class="chev">›</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { isLoggedIn } from "../../core/auth";
import { listCompanions } from "../../modules/companions/api";

type Companion = {
  companion_id: string;
  mbti: string;
  display_name: string;
  source: string;
};

const items = ref<Companion[]>([]);

async function load() {
  if (!isLoggedIn()) {
    uni.redirectTo({ url: "/pages/login/login" });
    return;
  }
  try {
    const res: any = await listCompanions();
    items.value = res.items || [];
  } catch (e: any) {
    uni.showToast({ title: e.message || "加载失败", icon: "none" });
  }
}

function goGacha() {
  uni.switchTab({ url: "/pages/gacha/gacha" });
}

function openChat(item: Companion) {
  uni.navigateTo({
    url: `/pages/chat/chat?companion_id=${encodeURIComponent(item.companion_id)}&mbti=${encodeURIComponent(item.mbti)}&name=${encodeURIComponent(item.display_name || item.mbti)}`,
  });
}

onShow(load);
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: linear-gradient(180deg, #f7f4ef 0%, #ebe4da 100%);
  padding: 48rpx 40rpx 120rpx;
}
.hero { margin-bottom: 48rpx; }
.title {
  display: block;
  font-size: 56rpx;
  font-weight: 700;
  color: #1c1b19;
  letter-spacing: -1rpx;
}
.sub {
  display: block;
  margin-top: 12rpx;
  color: #6f675f;
  font-size: 26rpx;
}
.empty {
  margin-top: 120rpx;
  text-align: center;
}
.empty-text {
  display: block;
  color: #6f675f;
  margin-bottom: 32rpx;
}
.primary {
  background: #1c1b19;
  color: #f7f4ef;
  border-radius: 999rpx;
  font-size: 28rpx;
}
.list { display: flex; flex-direction: column; gap: 20rpx; }
.row {
  display: flex;
  align-items: center;
  padding: 28rpx 24rpx;
  background: rgba(255, 250, 243, 0.9);
  border-radius: 24rpx;
}
.avatar {
  width: 80rpx;
  height: 80rpx;
  border-radius: 40rpx;
  background: #2f604f;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  margin-right: 24rpx;
}
.meta { flex: 1; }
.name { display: block; font-size: 32rpx; color: #1c1b19; font-weight: 600; }
.mbti { display: block; font-size: 24rpx; color: #82786d; margin-top: 4rpx; }
.chev { color: #c0b6a8; font-size: 40rpx; }
</style>
