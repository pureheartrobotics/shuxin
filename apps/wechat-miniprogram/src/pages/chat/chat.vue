<template>
  <view class="page">
    <view v-if="showPrivacyGate" class="privacy-overlay" @tap.stop>
      <view class="privacy-card" @tap.stop>
        <view class="privacy-title">隐私保护提示</view>
        <view class="privacy-desc">
          语音对话需要使用麦克风。请阅读并同意
          <text class="privacy-link" @tap="onOpenPrivacyContract">{{ privacyContractName }}</text>
          后再按住说话。
        </view>
        <view class="privacy-hint">若随后出现微信系统弹窗，请先勾选隐私协议再点「允许」。</view>
        <view class="privacy-actions">
          <button size="mini" @tap="onPrivacyDenied">暂不同意</button>
          <button
            id="chat-privacy-agree-btn"
            size="mini"
            open-type="agreePrivacyAuthorization"
            @agreeprivacyauthorization="onPrivacyAgreed"
          >
            同意并继续
          </button>
        </view>
      </view>
    </view>

    <view class="header">
      <text class="name">{{ name }}</text>
      <text class="mbti">{{ mbti }}</text>
      <text v-if="relationHeader" class="rel-line">{{ relationHeader }}</text>
      <text v-if="milestoneHeader" class="mile-line">{{ milestoneHeader }}</text>
      <text v-if="quotaLine" class="quota-line">{{ quotaLine }}</text>
    </view>
    <view v-if="careBanner" class="care-banner" @click="dismissCareBanner">
      <text>{{ careBanner }}</text>
    </view>
    <scroll-view scroll-y class="msgs" :scroll-into-view="scrollId">
      <view v-for="(m, i) in messages" :key="i" :id="'m' + i" class="bubble" :class="m.role">
        <text>{{ m.text }}</text>
      </view>
    </scroll-view>
    <view v-if="statusHint" class="hint">{{ statusHint }}</view>
    <view v-if="streakNudge" class="nudge">{{ streakNudge }}</view>
    <view class="composer">
      <input
        class="input"
        v-model="draft"
        :maxlength="500"
        placeholder="说点什么（最多500字）"
        confirm-type="send"
        :disabled="quotaBlocked"
        @confirm="sendText"
      />
      <button class="send" size="mini" :disabled="busy || quotaBlocked" @click="sendText">发送</button>
    </view>
    <view v-if="quotaBlocked" class="paywall">
      <text>陪伴点已用尽，充值后继续聊</text>
      <button size="mini" class="pay-btn" @click="goRecharge">去充值</button>
    </view>
    <view class="voice-bar">
      <button
        class="hold"
        :class="{ active: holding }"
        :disabled="!voiceReady || busy || quotaBlocked"
        @touchstart.prevent="onHoldStart"
        @touchend.prevent="onHoldEnd"
        @touchcancel.prevent="onHoldEnd"
      >
        {{ holdLabel }}
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { ApiError } from "../../core/http";
import { ackCare, chatText, fetchEngagement, softCredentials } from "../../modules/companions/api";
import { SoftVoiceSession } from "../../modules/companions/voice-ws";
import {
  CHAT_PRIVACY_AGREE_BUTTON_ID,
  PrivacyNeedAgreeError,
  assertRecordPrivacyAuthorized,
  loadPrivacyContractName,
  mapPrivacyError,
  mapWxPrivacyApiError,
  notifyPrivacyAgreed,
  notifyPrivacyDenied,
  openPrivacyContract,
  setPrivacyGateHandler,
} from "../../utils/privacy";
import { formatPointsLabel, minutesToPoints } from "../../utils/companion-points";

const companionId = ref("");
const mbti = ref("");
const name = ref("");
const draft = ref("");
const messages = ref<{ role: string; text: string }[]>([]);
const scrollId = ref("m0");
const busy = ref(false);
const holding = ref(false);
const voiceReady = ref(false);
const statusHint = ref("");
const liveAssistant = ref("");
const showPrivacyGate = ref(false);
const privacyContractName = ref("《用户隐私保护指引》");
const quotaBlocked = ref(false);
const quotaLine = ref("");
const careBanner = ref("");
const careKey = ref("");
const streakNudge = ref("");
const relationHeader = ref("");
const milestoneHeader = ref("");

let voice: SoftVoiceSession | null = null;
let softCreds: { device_id: string; device_secret: string } | null = null;
let pendingStartAfterPrivacy = false;

function isQuotaExhaustedMessage(raw: string) {
  return (
    raw.includes("quota_exhausted") ||
    raw.includes("额度已用尽") ||
    raw.includes("陪伴点已用尽")
  );
}

const holdLabel = computed(() => {
  if (quotaBlocked.value) return "陪伴点已用尽";
  if (!voiceReady.value) return "语音未就绪";
  if (holding.value) return "松开结束";
  return "按住 说话";
});

function pushMessage(role: string, text: string) {
  messages.value.push({ role, text });
  scrollId.value = "m" + (messages.value.length - 1);
}

function applyEngagement(eng: any) {
  if (!eng || typeof eng !== "object") return;
  const quota = eng.quota || {};
  quotaBlocked.value = Boolean(quota.exhausted);
  const daily = Number(quota.daily_allowance_left || 0);
  const remain = Number(quota.remain_yuan || 0);
  if (quota.exhausted) {
    quotaLine.value = "陪伴点已用尽";
  } else if (daily > 0) {
    quotaLine.value = `今日低保约剩 ${formatPointsLabel(daily)}`;
  } else {
    quotaLine.value = `可用约 ${formatPointsLabel(remain)}`;
  }
  const care = eng.care || {};
  if (care.unread && care.message) {
    careBanner.value = String(care.message);
    careKey.value = String(care.care_key || "");
  }
  const streak = eng.streak || {};
  streakNudge.value = String(streak.nudge || "");
  const rel = eng.relationship || {};
  const stage = String(rel.stage_label || "").trim();
  const hint = String(rel.next_hint || "").trim();
  relationHeader.value = stage
    ? hint
      ? `${stage} · ${hint}`
      : stage
    : "";
  const mile = rel.latest_milestone || {};
  const mileLabel = String(mile.label || "").trim();
  milestoneHeader.value = mileLabel ? `最近：${mileLabel}` : "";
}

function goRecharge() {
  uni.switchTab({ url: "/pages/profile/profile" });
}

async function dismissCareBanner() {
  const key = careKey.value;
  careBanner.value = "";
  if (!key) return;
  try {
    await ackCare(key, companionId.value);
  } catch {
    /* ignore */
  }
}

function promptQuotaPaywall(detail?: string) {
  quotaBlocked.value = true;
  statusHint.value = detail || "陪伴点已用尽，请充值";
  uni.showModal({
    title: "陪伴点已用尽",
    content: "充值后即可继续和伙伴聊天",
    confirmText: "去充值",
    success: (res) => {
      if (res.confirm) goRecharge();
    },
  });
}

onLoad(async (query: any) => {
  companionId.value = decodeURIComponent(query?.companion_id || "");
  mbti.value = decodeURIComponent(query?.mbti || "");
  name.value = decodeURIComponent(query?.name || "伙伴");
  statusHint.value = "正在准备语音通道…";
  privacyContractName.value = await loadPrivacyContractName();
  setPrivacyGateHandler(async () => {
    showPrivacyGate.value = true;
  });
  try {
    const eng: any = await fetchEngagement(companionId.value);
    applyEngagement(eng);
  } catch {
    /* optional */
  }
  try {
    const creds: any = await softCredentials();
    softCreds = {
      device_id: String(creds.device_id || ""),
      device_secret: String(creds.device_secret || ""),
    };
    if (!softCreds.device_id || !softCreds.device_secret) {
      throw new Error("soft credentials incomplete");
    }
    voice = new SoftVoiceSession(softCreds, companionId.value, {
      onReady: () => {
        voiceReady.value = true;
        if (!quotaBlocked.value) statusHint.value = "可文字或按住说话";
      },
      onStt: (text) => {
        statusHint.value = `听清：${text}`;
      },
      onDelta: (text) => {
        liveAssistant.value += text;
        statusHint.value = "回复中…";
      },
      onReply: (text) => {
        const body = text || liveAssistant.value;
        liveAssistant.value = "";
        if (body) pushMessage("assistant", body);
        statusHint.value = quotaBlocked.value ? "陪伴点已用尽" : "可文字或按住说话";
        busy.value = false;
        void fetchEngagement(companionId.value).then(applyEngagement).catch(() => undefined);
      },
      onError: (message) => {
        const mapped = mapWxPrivacyApiError(message);
        const raw = String(message || "");
        if (isQuotaExhaustedMessage(raw)) {
          promptQuotaPaywall(raw);
        } else {
          statusHint.value = mapped ? mapped.message : message;
        }
        busy.value = false;
        holding.value = false;
      },
      onBusy: (v) => {
        busy.value = v;
      },
    });
    await voice.connect();
  } catch (e: any) {
    voiceReady.value = false;
    statusHint.value = e?.message || "语音通道失败，仍可用文字";
  }
});

onUnmounted(() => {
  setPrivacyGateHandler(null);
  voice?.close();
  voice = null;
});

async function sendText() {
  const text = draft.value.trim();
  if (!text || !companionId.value || busy.value || quotaBlocked.value) return;
  pushMessage("user", text);
  draft.value = "";
  busy.value = true;
  statusHint.value = "发送中…";
  try {
    const res: any = await chatText(companionId.value, text);
    pushMessage("assistant", res.reply || "…");
    applyEngagement(res.engagement);
    const nudge = res.engagement?.streak?.nudge;
    if (nudge) {
      statusHint.value = String(nudge);
    } else {
      const est = res.usage?.estimate_minutes_typing;
      if (est != null) {
        const pts = minutesToPoints(Number(est));
        statusHint.value =
          pts == null
            ? "可文字或按住说话"
            : `本条约 ${pts} 陪伴点（实际按用量结算）`;
      } else {
        statusHint.value = "可文字或按住说话";
      }
    }
  } catch (e: any) {
    if (e instanceof ApiError && e.code === "quota_exhausted") {
      applyEngagement(e.body?.engagement || { quota: e.body?.quota });
      promptQuotaPaywall(e.detail);
    } else {
      pushMessage("assistant", e.message || "发送失败");
      statusHint.value = e.message || "发送失败";
    }
  } finally {
    busy.value = false;
  }
}

async function beginListen() {
  if (!voiceReady.value || !voice || busy.value || quotaBlocked.value) return;
  holding.value = true;
  liveAssistant.value = "";
  statusHint.value = "聆听中…";
  try {
    voice.startListen();
  } catch (e: any) {
    holding.value = false;
    const msg = String(e?.errMsg || e?.message || "");
    const mapped = mapWxPrivacyApiError(msg);
    statusHint.value = mapped ? mapped.message : msg || "录音失败";
    if (mapped || msg.toLowerCase().includes("scope is not declared")) {
      showPrivacyGate.value = true;
    }
  }
}

async function onHoldStart() {
  if (!voiceReady.value || !voice || busy.value || quotaBlocked.value) return;
  try {
    await assertRecordPrivacyAuthorized();
  } catch (e) {
    if (e instanceof PrivacyNeedAgreeError) {
      privacyContractName.value = e.privacyContractName;
      pendingStartAfterPrivacy = true;
      showPrivacyGate.value = true;
      statusHint.value = mapPrivacyError(e) || "请先同意隐私指引";
      return;
    }
    const mapped = mapPrivacyError(e);
    statusHint.value = mapped || "隐私检查失败";
    return;
  }
  await beginListen();
}

function onHoldEnd() {
  if (!holding.value || !voice) return;
  holding.value = false;
  statusHint.value = "识别中…";
  voice.stopListen();
}

function onOpenPrivacyContract() {
  void openPrivacyContract().catch(() => {
    /* ignore */
  });
}

function onPrivacyAgreed() {
  notifyPrivacyAgreed(CHAT_PRIVACY_AGREE_BUTTON_ID);
  showPrivacyGate.value = false;
  if (pendingStartAfterPrivacy) {
    pendingStartAfterPrivacy = false;
    void beginListen();
  }
}

function onPrivacyDenied() {
  notifyPrivacyDenied();
  showPrivacyGate.value = false;
  pendingStartAfterPrivacy = false;
  statusHint.value = "已拒绝麦克风隐私授权";
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
.rel-line {
  display: block;
  margin-top: 8rpx;
  font-size: 22rpx;
  color: #4a5c52;
}
.mile-line {
  display: block;
  margin-top: 4rpx;
  font-size: 22rpx;
  color: #2f604f;
}
.quota-line {
  display: block;
  margin-top: 8rpx;
  font-size: 22rpx;
  color: #6f675f;
}
.care-banner {
  margin: 16rpx 24rpx 0;
  padding: 20rpx 24rpx;
  background: #2f604f;
  color: #f7f4ef;
  border-radius: 16rpx;
  font-size: 26rpx;
}
.nudge {
  padding: 4rpx 28rpx 12rpx;
  font-size: 22rpx;
  color: #9a6c2e;
}
.paywall {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
  padding: 16rpx 24rpx;
  background: #fff3e6;
  color: #6f3f12;
  font-size: 24rpx;
}
.pay-btn {
  background: #2f604f;
  color: #fff;
  border-radius: 999rpx;
}
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
.hint {
  padding: 8rpx 28rpx;
  font-size: 22rpx;
  color: #8a7f72;
}
.composer {
  display: flex;
  gap: 12rpx;
  padding: 16rpx 24rpx;
  background: #fffaf3;
  border-top: 1rpx solid #e7dfd4;
}
.input {
  flex: 1;
  background: #fff;
  border-radius: 999rpx;
  padding: 12rpx 24rpx;
  font-size: 28rpx;
}
.send {
  background: #2f604f;
  color: #fff;
  border-radius: 999rpx;
}
.voice-bar {
  padding: 12rpx 24rpx 36rpx;
  background: #fffaf3;
}
.hold {
  width: 100%;
  border-radius: 999rpx;
  background: linear-gradient(180deg, #c9954a, #9a6c2e);
  color: #fffaf0;
  font-weight: 700;
  border: none;
}
.hold.active {
  background: linear-gradient(180deg, #2f604f, #1f4034);
}
.hold[disabled] {
  opacity: 0.5;
}
.privacy-overlay {
  position: fixed;
  left: 0;
  right: 0;
  top: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.45);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48rpx;
}
.privacy-card {
  background: #fffaf3;
  border-radius: 24rpx;
  padding: 36rpx;
  width: 100%;
}
.privacy-title {
  font-size: 32rpx;
  font-weight: 700;
  margin-bottom: 16rpx;
}
.privacy-desc,
.privacy-hint {
  font-size: 26rpx;
  color: #5c5349;
  line-height: 1.5;
  margin-bottom: 12rpx;
}
.privacy-link {
  color: #2f604f;
  text-decoration: underline;
}
.privacy-actions {
  display: flex;
  justify-content: flex-end;
  gap: 16rpx;
  margin-top: 24rpx;
}
</style>
