<template>
  <view class="page">
    <view class="hero">
      <text class="title">我的伙伴</text>
      <text class="sub">免费抽卡养性格 · 文字与语音都能聊</text>
    </view>

    <view v-if="quotaHint" class="quota">
      <text>{{ quotaHint }}</text>
      <text v-if="quotaExhausted" class="quota-link" @click="goRecharge">去充值</text>
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
          <text v-if="relationLine(item)" class="rel">{{ relationLine(item) }}</text>
          <text v-if="milestoneLine(item)" class="mile">{{ milestoneLine(item) }}</text>
          <view
            v-if="item.care && item.care.unread && item.care.message"
            class="care-inline"
            @click.stop="dismissItemCare(item)"
          >
            <text class="care-inline-label">想你了</text>
            <text class="care-inline-text">{{ item.care.message }}</text>
          </view>
        </view>
        <text class="chev">›</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { isLoggedIn } from "../../core/auth";
import { ackCare, listCompanions } from "../../modules/companions/api";
import { formatPointsLabel } from "../../utils/companion-points";

type Relationship = {
  stage_id?: string;
  stage_label?: string;
  next_hint?: string;
  latest_milestone?: { id?: string; label?: string; at?: string } | null;
};

type Companion = {
  companion_id: string;
  mbti: string;
  display_name: string;
  source: string;
  relationship?: Relationship;
  care?: { unread?: boolean; message?: string; care_key?: string };
};

const items = ref<Companion[]>([]);
const remainYuan = ref<number | null>(null);
const dailyLeft = ref<number | null>(null);
const quotaExhausted = ref(false);

const quotaHint = computed(() => {
  if (quotaExhausted.value) return "今日陪伴点已用尽";
  if (dailyLeft.value != null && dailyLeft.value > 0) {
    return `今日低保约剩 ${formatPointsLabel(dailyLeft.value)}`;
  }
  if (remainYuan.value != null) {
    return `可用约 ${formatPointsLabel(remainYuan.value)}`;
  }
  return "";
});

function relationLine(item: Companion) {
  const rel = item.relationship || {};
  const stage = String(rel.stage_label || "").trim();
  const hint = String(rel.next_hint || "").trim();
  if (!stage) return "";
  return hint ? `关系：${stage} · ${hint}` : `关系：${stage}`;
}

function milestoneLine(item: Companion) {
  const label = String(item.relationship?.latest_milestone?.label || "").trim();
  return label ? `我们一起 · ${label}` : "";
}

async function load() {
  if (!isLoggedIn()) {
    uni.redirectTo({ url: "/pages/login/login" });
    return;
  }
  try {
    const res: any = await listCompanions();
    items.value = res.items || [];
    const eng = res.engagement || {};
    const quota = eng.quota || {};
    remainYuan.value = quota.remain_yuan != null ? Number(quota.remain_yuan) : null;
    dailyLeft.value =
      quota.daily_allowance_left != null ? Number(quota.daily_allowance_left) : null;
    quotaExhausted.value = Boolean(quota.exhausted);
    try {
      if (uni.getStorageSync("shuxin_partners_dirty") === "1") {
        uni.removeStorageSync("shuxin_partners_dirty");
      }
    } catch {
      /* ignore */
    }
  } catch (e: any) {
    uni.showToast({ title: e.message || "加载失败", icon: "none" });
  }
}

async function dismissItemCare(item: Companion) {
  const key = String(item.care?.care_key || "");
  if (item.care) {
    item.care.unread = false;
    item.care.message = "";
  }
  if (!key) return;
  try {
    await ackCare(key, item.companion_id);
  } catch {
    /* ignore */
  }
}

function goGacha() {
  uni.switchTab({ url: "/pages/gacha/gacha" });
}

function goRecharge() {
  uni.switchTab({ url: "/pages/profile/profile" });
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
.hero { margin-bottom: 32rpx; }
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
.quota {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24rpx;
  padding: 16rpx 20rpx;
  background: rgba(255, 250, 243, 0.9);
  border-radius: 16rpx;
  color: #6f675f;
  font-size: 24rpx;
}
.quota-link {
  color: #2f604f;
  font-weight: 600;
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
  font-size: 32rpx;
  margin-right: 20rpx;
}
.meta { flex: 1; }
.name {
  display: block;
  font-size: 30rpx;
  color: #1c1b19;
  font-weight: 600;
}
.mbti {
  display: block;
  margin-top: 6rpx;
  font-size: 22rpx;
  color: #6f675f;
}
.rel {
  display: block;
  margin-top: 8rpx;
  font-size: 22rpx;
  color: #4a5c52;
}
.mile {
  display: block;
  margin-top: 4rpx;
  font-size: 22rpx;
  color: #2f604f;
}
.care-inline {
  margin-top: 12rpx;
  padding: 12rpx 14rpx;
  background: #2f604f;
  border-radius: 12rpx;
  color: #f7f4ef;
}
.care-inline-label {
  display: block;
  font-size: 20rpx;
  opacity: 0.8;
}
.care-inline-text {
  display: block;
  margin-top: 4rpx;
  font-size: 24rpx;
  line-height: 1.4;
}
.chev { color: #b0a89e; font-size: 40rpx; }
</style>
