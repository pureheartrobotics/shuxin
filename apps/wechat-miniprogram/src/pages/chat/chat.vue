<template>
  <view class="page">
    <view class="header">
      <text class="name">{{ name }}</text>
      <text class="mbti">{{ mbti }}</text>
    </view>
    <scroll-view scroll-y class="msgs" :scroll-into-view="scrollId">
      <view v-for="(m, i) in messages" :key="i" :id="'m' + i" class="bubble" :class="m.role">
        <text>{{ m.text }}</text>
      </view>
    </scroll-view>
    <view class="composer">
      <input
        class="input"
        v-model="draft"
        :maxlength="500"
        placeholder="说点什么（最多500字）"
        confirm-type="send"
        @confirm="sendText"
      />
      <button class="send" size="mini" @click="sendText">发送</button>
    </view>
    <view class="voice-hint">语音：取得 soft 凭证后可用硬件同款 WS（demo 请先用文字）</view>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { chatText, softCredentials } from "../../modules/companions/api";

const companionId = ref("");
const mbti = ref("");
const name = ref("");
const draft = ref("");
const messages = ref<{ role: string; text: string }[]>([]);
const scrollId = ref("m0");
const softReady = ref(false);

onLoad(async (query: any) => {
  companionId.value = decodeURIComponent(query?.companion_id || "");
  mbti.value = decodeURIComponent(query?.mbti || "");
  name.value = decodeURIComponent(query?.name || "伙伴");
  try {
    await softCredentials();
    softReady.value = true;
  } catch (e) {
    softReady.value = false;
  }
});

async function sendText() {
  const text = draft.value.trim();
  if (!text || !companionId.value) return;
  messages.value.push({ role: "user", text });
  draft.value = "";
  scrollId.value = "m" + (messages.value.length - 1);
  try {
    const res: any = await chatText(companionId.value, text);
    messages.value.push({ role: "assistant", text: res.reply || "…" });
  } catch (e: any) {
    messages.value.push({ role: "assistant", text: e.message || "发送失败" });
  }
  scrollId.value = "m" + (messages.value.length - 1);
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f4f0ea;
}
.header {
  padding: 24rpx 32rpx;
  background: #fffaf3;
  border-bottom: 1rpx solid #e7dfd4;
}
.name { font-size: 34rpx; font-weight: 700; color: #1c1b19; margin-right: 16rpx; }
.mbti { font-size: 24rpx; color: #82786d; }
.msgs { flex: 1; padding: 24rpx; height: 0; }
.bubble {
  max-width: 80%;
  margin-bottom: 20rpx;
  padding: 20rpx 24rpx;
  border-radius: 24rpx;
  font-size: 28rpx;
  line-height: 1.5;
}
.bubble.user {
  margin-left: auto;
  background: #2f604f;
  color: #fff;
}
.bubble.assistant {
  background: #fff;
  color: #1c1b19;
}
.composer {
  display: flex;
  gap: 16rpx;
  padding: 16rpx 24rpx 8rpx;
  background: #fffaf3;
  align-items: center;
}
.input {
  flex: 1;
  background: #fff;
  border-radius: 999rpx;
  padding: 16rpx 28rpx;
  font-size: 28rpx;
}
.send { background: #1c1b19; color: #fff; }
.voice-hint {
  text-align: center;
  font-size: 22rpx;
  color: #9a9085;
  padding-bottom: 24rpx;
  background: #fffaf3;
}
</style>
