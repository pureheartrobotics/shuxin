<template>
  <view class="page">
    <view class="top">
      <text class="label">免费次数</text>
      <text class="count">{{ remaining }} / {{ freeTotal }}</text>
    </view>

    <view class="machine" :class="{ revealing: revealFlash }">
      <view
        v-for="(ch, idx) in reels"
        :key="idx"
        class="reel"
        :class="{ spinning: reelSpinning[idx], locked: reelLocked[idx] }"
      >
        <text class="letter">{{ ch }}</text>
      </view>
    </view>

    <button class="draw" :disabled="busy" @click="onDraw">
      {{ remaining > 0 ? '摇一把' : `¥${price} 再抽一次` }}
    </button>

    <view v-if="showResult && result" class="result" :class="{ pop: showResult }">
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

const LETTERS = ["E", "I", "S", "N", "T", "F", "J", "P"];

const remaining = ref(3);
const freeTotal = ref(3);
const price = ref(9.9);
const reels = ref(["?", "?", "?", "?"]);
const reelSpinning = ref([false, false, false, false]);
const reelLocked = ref([false, false, false, false]);
const busy = ref(false);
const result = ref<any>(null);
const showResult = ref(false);
const revealFlash = ref(false);

let spinTimers: ReturnType<typeof setInterval>[] = [];

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

function clearSpinTimers() {
  spinTimers.forEach((t) => clearInterval(t));
  spinTimers = [];
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function animateReels(mbti: string) {
  clearSpinTimers();
  showResult.value = false;
  revealFlash.value = false;
  const target = (mbti || "????").toUpperCase().slice(0, 4).padEnd(4, "?").split("");
  reelLocked.value = [false, false, false, false];
  reelSpinning.value = [true, true, true, true];

  // 四格同时乱刷
  for (let i = 0; i < 4; i++) {
    const idx = i;
    spinTimers.push(
      setInterval(() => {
        if (!reelSpinning.value[idx]) return;
        const next = [...reels.value];
        next[idx] = LETTERS[Math.floor(Math.random() * LETTERS.length)];
        reels.value = next;
      }, 70 + idx * 12)
    );
  }

  await sleep(1400);

  // 左→右停稳
  for (let i = 0; i < 4; i++) {
    await sleep(280);
    reelSpinning.value = reelSpinning.value.map((v, j) => (j === i ? false : v));
    const next = [...reels.value];
    next[i] = target[i];
    reels.value = next;
    const locked = [...reelLocked.value];
    locked[i] = true;
    reelLocked.value = locked;
  }

  clearSpinTimers();
  await sleep(180);
  revealFlash.value = true;
  await sleep(420);
  revealFlash.value = false;
  showResult.value = true;
}

async function onDraw() {
  if (busy.value) return;
  busy.value = true;
  result.value = null;
  showResult.value = false;
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
    result.value = companion;
    remaining.value = Number(res.free_gacha_remaining ?? remaining.value);
    await animateReels(companion.mbti || (res.letters || []).join(""));
  } catch (e: any) {
    clearSpinTimers();
    reelSpinning.value = [false, false, false, false];
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
  background:
    radial-gradient(ellipse at 50% 0%, rgba(196, 149, 74, 0.28), transparent 55%),
    linear-gradient(180deg, #f3ebe0 0%, #e4d8c8 48%, #d5c7b4 100%);
}
.top {
  display: flex;
  justify-content: space-between;
  margin-bottom: 48rpx;
}
.label { color: #6f675f; font-size: 26rpx; }
.count { font-weight: 700; color: #1c1b19; font-size: 30rpx; }
.machine {
  display: flex;
  gap: 18rpx;
  justify-content: center;
  margin: 72rpx 0 56rpx;
  padding: 28rpx;
  border-radius: 32rpx;
  background: linear-gradient(160deg, #2a241c, #15120e);
  box-shadow:
    inset 0 1rpx 0 rgba(255, 220, 160, 0.25),
    0 24rpx 60rpx rgba(40, 28, 12, 0.35);
  transition: box-shadow 0.35s ease;
}
.machine.revealing {
  box-shadow:
    inset 0 1rpx 0 rgba(255, 230, 180, 0.55),
    0 0 0 4rpx rgba(212, 160, 72, 0.55),
    0 28rpx 70rpx rgba(40, 28, 12, 0.4);
}
.reel {
  width: 128rpx;
  height: 176rpx;
  border-radius: 22rpx;
  background: linear-gradient(180deg, #3a3228, #1a1612);
  color: #f4ead8;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2rpx solid rgba(212, 160, 72, 0.35);
  overflow: hidden;
}
.reel.spinning .letter {
  animation: reelFlicker 0.09s steps(2) infinite;
  opacity: 0.85;
}
.reel.locked {
  border-color: rgba(232, 188, 96, 0.85);
  background: linear-gradient(180deg, #4a3c28, #241c14);
}
.letter {
  font-size: 72rpx;
  font-weight: 800;
  letter-spacing: 2rpx;
  font-family: "DIN Alternate", "Helvetica Neue", Arial, sans-serif;
}
@keyframes reelFlicker {
  from { transform: translateY(-10rpx); }
  to { transform: translateY(10rpx); }
}
.draw {
  background: linear-gradient(180deg, #c9954a, #9a6c2e);
  color: #fffaf0;
  border-radius: 999rpx;
  font-weight: 700;
  border: none;
  box-shadow: 0 12rpx 28rpx rgba(120, 80, 20, 0.28);
}
.draw[disabled] { opacity: 0.55; }
.result {
  margin-top: 48rpx;
  padding: 36rpx;
  border-radius: 28rpx;
  background: rgba(255, 250, 243, 0.92);
  text-align: center;
  border: 1rpx solid rgba(170, 140, 90, 0.35);
  opacity: 0;
  transform: translateY(24rpx) scale(0.96);
}
.result.pop {
  animation: resultPop 0.45s cubic-bezier(0.2, 0.9, 0.2, 1.15) forwards;
}
@keyframes resultPop {
  to { opacity: 1; transform: translateY(0) scale(1); }
}
.result-title { display: block; font-size: 40rpx; font-weight: 800; color: #1c1b19; }
.result-mbti { display: block; margin: 12rpx 0 28rpx; color: #7a6f62; letter-spacing: 6rpx; }
.secondary {
  background: #2f604f;
  color: #fff;
  border-radius: 999rpx;
  border: none;
}
</style>
