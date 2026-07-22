<template>
  <view class="page">
    <view class="top">
      <text class="label">免费次数</text>
      <text class="count">{{ remaining }} / {{ freeTotal }}</text>
    </view>
    <view class="machine">
      <view v-for="(ch, idx) in reels" :key="idx" class="reel" :class="{ spin: spinning }">
        <text class="letter">{{ ch }}</text>
      </view>
    </view>
    <button class="draw" :disabled="busy" @click="onDraw">
      {{ remaining > 0 ? '摇一把' : `¥${price} 再抽一次` }}
    </button>
    <view v-if="result" class="result">
      <text class="result-title">{{ result.display_name }}</text>
      <text class="result-mbti">{{ result.mbti }}</text>
      <button class="secondary" @click="goChat">开始聊天</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { isLoggedIn } from "../../core/auth";
import { createGachaOrder, drawGacha, fetchGachaConfig } from "../../modules/companions/api";
import { invokeWechatPay } from "../../modules/account/api/payment-quota";

const remaining = ref(3);
const freeTotal = ref(3);
const price = ref(9.9);
const reels = ref(["?", "?", "?", "?"]);
const spinning = ref(false);
const busy = ref(false);
const result = ref<any>(null);

async function loadConfig() {
  if (!isLoggedIn()) {
    uni.redirectTo({ url: "/pages/login/login" });
    return;
  }
  const cfg: any = await fetchGachaConfig();
  remaining.value = Number(cfg.free_gacha_remaining ?? 0);
  freeTotal.value = Number(cfg.free_draws_per_user ?? 3);
  price.value = Number(cfg.paid_draw_price_yuan ?? 9.9);
}

function animateTo(mbti: string) {
  spinning.value = true;
  const letters = (mbti || "????").toUpperCase().slice(0, 4).split("");
  reels.value = ["·", "·", "·", "·"];
  letters.forEach((ch, i) => {
    setTimeout(() => {
      const next = [...reels.value];
      next[i] = ch;
      reels.value = next;
      if (i === letters.length - 1) spinning.value = false;
    }, 400 + i * 450);
  });
}

async function onDraw() {
  if (busy.value) return;
  busy.value = true;
  result.value = null;
  try {
    let payment_id: string | undefined;
    if (remaining.value <= 0) {
      const orderRes: any = await createGachaOrder();
      if (orderRes.mock_paid) {
        payment_id = orderRes.order?.order_id;
      } else if (orderRes.pay_params) {
        await invokeWechatPay(orderRes.pay_params);
        payment_id = orderRes.order?.order_id;
      } else {
        throw new Error(orderRes.error || "支付不可用");
      }
    }
    const res: any = await drawGacha(payment_id);
    const companion = res.companion || {};
    animateTo(companion.mbti || (res.letters || []).join(""));
    result.value = companion;
    remaining.value = Number(res.free_gacha_remaining ?? remaining.value);
  } catch (e: any) {
    uni.showToast({ title: e.message || "抽卡失败", icon: "none" });
  } finally {
    busy.value = false;
  }
}

function goChat() {
  if (!result.value) return;
  uni.navigateTo({
    url: `/pages/chat/chat?companion_id=${encodeURIComponent(result.value.companion_id)}&mbti=${encodeURIComponent(result.value.mbti)}&name=${encodeURIComponent(result.value.display_name || result.value.mbti)}`,
  });
}

onShow(loadConfig);
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 48rpx 40rpx;
  background: radial-gradient(circle at 50% 20%, #fff7e8, #e8dfd3 60%, #d9cfc0);
}
.top { display: flex; justify-content: space-between; margin-bottom: 48rpx; }
.label { color: #6f675f; }
.count { font-weight: 700; color: #1c1b19; }
.machine {
  display: flex;
  gap: 16rpx;
  justify-content: center;
  margin: 80rpx 0;
}
.reel {
  width: 120rpx;
  height: 160rpx;
  border-radius: 24rpx;
  background: #1c1b19;
  color: #f7f4ef;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 16rpx 40rpx rgba(0,0,0,0.2);
}
.reel.spin { animation: pulse 0.35s ease-in-out infinite alternate; }
@keyframes pulse { from { transform: translateY(0); } to { transform: translateY(-8rpx); } }
.letter { font-size: 64rpx; font-weight: 700; }
.draw {
  background: #c45c26;
  color: #fff;
  border-radius: 999rpx;
  font-size: 32rpx;
  font-weight: 600;
}
.result {
  margin-top: 48rpx;
  text-align: center;
  padding: 40rpx;
  background: rgba(255,250,243,0.92);
  border-radius: 32rpx;
}
.result-title { display: block; font-size: 40rpx; font-weight: 700; }
.result-mbti { display: block; margin: 12rpx 0 32rpx; color: #6f675f; }
.secondary {
  background: #1c1b19;
  color: #f7f4ef;
  border-radius: 999rpx;
}
</style>
