<template>
  <view class="page">
    <view v-if="showPrivacyGate" class="privacy-overlay" @tap.stop>
      <view class="privacy-card" @tap.stop>
        <view class="privacy-title">隐私保护提示</view>
        <view class="privacy-desc">
          语音对话需要使用麦克风。请阅读并同意
          <text class="privacy-link" @tap="onOpenPrivacyContract">{{ privacyContractName }}</text>
          后再继续。
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
      <view class="header-card">
        <view class="header-row">
          <view class="header-identity">
            <text class="name">{{ name }}</text>
            <text class="mbti">{{ mbti }}</text>
          </view>
          <button
            v-if="mode === 'text'"
            class="mode-btn"
            size="mini"
            :disabled="quotaBlocked || busy"
            @tap="enterVoiceCall"
          >
            语音通话
          </button>
          <button v-else class="mode-btn hangup" size="mini" @tap="hangUpVoice">挂断</button>
        </view>
        <text v-if="mode === 'voice'" class="call-badge">通话中 · 说完一句自动回复</text>
        <text v-if="relationHeader" class="rel-line">{{ relationHeader }}</text>
        <text v-if="milestoneHeader" class="mile-line">{{ milestoneHeader }}</text>
        <text v-if="quotaLine" class="quota-line">{{ quotaLine }}</text>
      </view>
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
    <view v-if="mode === 'text'" class="composer">
      <input
        class="input"
        v-model="draft"
        :maxlength="500"
        placeholder="说点什么（最多500字）"
        confirm-type="send"
        :disabled="quotaBlocked || busy"
        @confirm="sendText"
      />
      <button class="send" size="mini" :disabled="busy || quotaBlocked" @click="sendText">发送</button>
    </view>
    <view v-if="quotaBlocked" class="paywall">
      <text>陪伴点已用尽，充值后继续聊</text>
      <button size="mini" class="pay-btn" @click="goRecharge">去充值</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { onUnmounted, ref } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { ApiError } from "../../core/http";
import {
  ackCare,
  chatText,
  chatTextStream,
  fetchEngagement,
  softCredentials,
} from "../../modules/companions/api";
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
import { formatPointsLabel } from "../../utils/companion-points";

const companionId = ref("");
const mbti = ref("");
const name = ref("");
const draft = ref("");
const messages = ref<{ role: string; text: string }[]>([]);
const scrollId = ref("m0");
const busy = ref(false);
const mode = ref<"text" | "voice">("text");
const statusHint = ref("");
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
let pendingEnterVoice = false;
let streamAssistantIndex = -1;
let voiceUserBubbleIndex = -1;
let voiceAssistantIndex = -1;

function isQuotaExhaustedMessage(raw: string) {
  return (
    raw.includes("quota_exhausted") ||
    raw.includes("额度已用尽") ||
    raw.includes("陪伴点已用尽")
  );
}

function pushMessage(role: string, text: string) {
  messages.value.push({ role, text });
  scrollId.value = "m" + (messages.value.length - 1);
  return messages.value.length - 1;
}

function appendToMessage(index: number, text: string) {
  if (index < 0 || index >= messages.value.length) return;
  const cur = messages.value[index];
  messages.value.splice(index, 1, { role: cur.role, text: cur.text + text });
  scrollId.value = "m" + index;
}

function setMessage(index: number, text: string) {
  if (index < 0 || index >= messages.value.length) return;
  const cur = messages.value[index];
  messages.value.splice(index, 1, { role: cur.role, text });
  scrollId.value = "m" + index;
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
  relationHeader.value = stage ? (hint ? `${stage} · ${hint}` : stage) : "";
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
  statusHint.value = "文字聊天可直接发送";
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
  } catch {
    softCreds = null;
  }
});

onUnmounted(() => {
  setPrivacyGateHandler(null);
  voice?.close();
  voice = null;
});

function sendText() {
  const text = draft.value.trim();
  if (!text || !companionId.value || busy.value || quotaBlocked.value || mode.value !== "text") {
    return;
  }
  pushMessage("user", text);
  draft.value = "";
  busy.value = true;
  statusHint.value = "回复中…";
  streamAssistantIndex = pushMessage("assistant", "");

  const finishOk = (res: any) => {
    if (streamAssistantIndex >= 0 && !(messages.value[streamAssistantIndex]?.text || "").trim()) {
      setMessage(streamAssistantIndex, String(res.reply || "…"));
    }
    applyEngagement(res.engagement);
    const nudge = res.engagement?.streak?.nudge;
    if (nudge) {
      statusHint.value = String(nudge);
    } else {
      statusHint.value = messages.value.length > 2 ? "可以说点什么" : "在呢，慢慢说";
    }
    busy.value = false;
    streamAssistantIndex = -1;
  };

  const fail = (e: any) => {
    if (e instanceof ApiError && e.code === "quota_exhausted") {
      applyEngagement(e.body?.engagement || { quota: e.body?.quota });
      promptQuotaPaywall(e.detail);
    } else {
      if (streamAssistantIndex >= 0) {
        setMessage(streamAssistantIndex, e.message || "发送失败");
      } else {
        pushMessage("assistant", e.message || "发送失败");
      }
      statusHint.value = e.message || "发送失败";
    }
    busy.value = false;
    streamAssistantIndex = -1;
  };

  chatTextStream(companionId.value, text, {
    onDelta: (piece) => {
      if (streamAssistantIndex >= 0) appendToMessage(streamAssistantIndex, piece);
    },
    onDone: (body) => finishOk(body),
    onError: (err) => {
      // chunked 不可用时回退整段接口
      void chatText(companionId.value, text)
        .then(finishOk)
        .catch(() => fail(err));
    },
  });
}

async function enterVoiceCall() {
  if (quotaBlocked.value || busy.value || mode.value === "voice") return;
  if (!softCreds?.device_id || !softCreds?.device_secret) {
    statusHint.value = "语音通道未就绪";
    return;
  }
  try {
    await assertRecordPrivacyAuthorized();
  } catch (e) {
    if (e instanceof PrivacyNeedAgreeError) {
      privacyContractName.value = e.privacyContractName;
      pendingEnterVoice = true;
      showPrivacyGate.value = true;
      statusHint.value = mapPrivacyError(e) || "请先同意隐私指引";
      return;
    }
    statusHint.value = mapPrivacyError(e) || "隐私检查失败";
    return;
  }
  await startContinuousVoice();
}

async function startContinuousVoice() {
  mode.value = "voice";
  statusHint.value = "正在连接语音…";
  voiceUserBubbleIndex = -1;
  voiceAssistantIndex = -1;
  voice?.close();
  voice = new SoftVoiceSession(softCreds!, companionId.value, {
    onReady: () => {
      statusHint.value = "请说话，说完一句会自动回复";
      voice?.startListen();
    },
    onStt: (text, state) => {
      if (!text) return;
      if (state === "partial") {
        statusHint.value = `听清：${text}`;
        return;
      }
      if (state === "sentence_final" || state === "final") {
        if (voiceUserBubbleIndex < 0) {
          voiceUserBubbleIndex = pushMessage("user", text);
        } else {
          setMessage(voiceUserBubbleIndex, text);
        }
        voiceAssistantIndex = -1;
      }
    },
    onThinking: () => {
      statusHint.value = "思考中…";
      busy.value = true;
    },
    onDelta: (piece) => {
      if (voiceAssistantIndex < 0) {
        voiceAssistantIndex = pushMessage("assistant", piece);
      } else {
        appendToMessage(voiceAssistantIndex, piece);
      }
    },
    onReply: (text) => {
      const body = String(text || "").trim() || "（没有听清文字，请再说一次）";
      if (voiceAssistantIndex < 0) {
        voiceAssistantIndex = pushMessage("assistant", body);
      } else if (!(messages.value[voiceAssistantIndex]?.text || "").trim()) {
        setMessage(voiceAssistantIndex, body);
      }
      voiceUserBubbleIndex = -1;
      void fetchEngagement(companionId.value).then(applyEngagement).catch(() => undefined);
    },
    onTtsIdle: () => {
      busy.value = false;
      if (mode.value === "voice") statusHint.value = "请继续说";
    },
    onError: (message) => {
      const mapped = mapWxPrivacyApiError(message);
      const raw = String(message || "");
      if (isQuotaExhaustedMessage(raw)) {
        promptQuotaPaywall(raw);
        hangUpVoice();
      } else if (raw.includes("tts_failed") || raw.includes("语音合成")) {
        // 保留提示；不要被后续「请继续说」盖掉（voice-ws stickyError）
        statusHint.value = mapped ? mapped.message : raw.includes("语音合成") ? raw : "语音播放失败";
      } else {
        statusHint.value = mapped ? mapped.message : message;
      }
      busy.value = false;
    },
    onBusy: (v) => {
      busy.value = v;
    },
  });
  try {
    await voice.connect({ conversationMode: "continuous" });
  } catch (e: any) {
    mode.value = "text";
    statusHint.value = e?.message || "语音连接失败";
    voice?.close();
    voice = null;
  }
}

function hangUpVoice() {
  voice?.close();
  voice = null;
  mode.value = "text";
  busy.value = false;
  statusHint.value = "已挂断，可继续文字聊天";
  voiceUserBubbleIndex = -1;
  voiceAssistantIndex = -1;
}

function onOpenPrivacyContract() {
  void openPrivacyContract().catch(() => {
    /* ignore */
  });
}

function onPrivacyAgreed() {
  notifyPrivacyAgreed(CHAT_PRIVACY_AGREE_BUTTON_ID);
  showPrivacyGate.value = false;
  if (pendingEnterVoice) {
    pendingEnterVoice = false;
    void startContinuousVoice();
  }
}

function onPrivacyDenied() {
  notifyPrivacyDenied();
  showPrivacyGate.value = false;
  pendingEnterVoice = false;
  statusHint.value = "已拒绝麦克风隐私授权";
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background:
    radial-gradient(ellipse at 20% 0%, rgba(255, 248, 236, 0.95), transparent 50%),
    linear-gradient(180deg, #f8f1e7 0%, #f4eee8 48%, #ece7df 100%);
}
.header {
  padding: 20rpx 28rpx 8rpx;
}
.header-card {
  padding: 28rpx 32rpx;
  border-radius: 28rpx;
  background: rgba(255, 252, 246, 0.88);
  border: 1rpx solid rgba(231, 223, 212, 0.9);
  box-shadow: 0 8rpx 28rpx rgba(74, 58, 40, 0.04);
}
.header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
}
.header-identity {
  display: flex;
  flex-direction: column;
  gap: 6rpx;
  min-width: 0;
}
.name {
  font-size: 36rpx;
  font-weight: 700;
  color: #24211c;
  letter-spacing: 0.02em;
}
.mbti {
  font-size: 24rpx;
  color: #9a9186;
}
.mode-btn {
  flex-shrink: 0;
  margin: 0;
  padding: 0 28rpx;
  line-height: 56rpx;
  background: #e4eee8;
  color: #2f604f;
  border-radius: 999rpx;
  font-weight: 600;
  border: none;
}
.mode-btn.hangup {
  background: #f3ded9;
  color: #9e3b35;
}
.call-badge {
  display: block;
  margin-top: 14rpx;
  font-size: 22rpx;
  color: #6f665b;
  font-weight: 500;
}
.rel-line {
  display: block;
  margin-top: 10rpx;
  font-size: 22rpx;
  color: #4a5d52;
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
  color: #9a9186;
}
.care-banner {
  margin: 12rpx 28rpx 0;
  padding: 20rpx 24rpx;
  background: #2f604f;
  color: #f7f4ef;
  border-radius: 20rpx;
  font-size: 26rpx;
}
.nudge {
  padding: 4rpx 32rpx 12rpx;
  font-size: 22rpx;
  color: #9b6146;
}
.paywall {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
  margin: 0 28rpx 12rpx;
  padding: 18rpx 24rpx;
  background: rgba(255, 243, 230, 0.95);
  color: #6f3f12;
  font-size: 24rpx;
  border-radius: 20rpx;
}
.pay-btn {
  background: #2f604f;
  color: #fffaf3;
  border-radius: 999rpx;
}
.msgs {
  flex: 1;
  padding: 20rpx 28rpx;
  height: 0;
}
.bubble {
  max-width: 78%;
  margin-bottom: 24rpx;
  padding: 22rpx 28rpx;
  border-radius: 28rpx;
  font-size: 30rpx;
  line-height: 1.55;
  animation: bubble-in 0.28s ease-out;
}
.bubble.user {
  margin-left: auto;
  background: #2f604f;
  color: #fffaf3;
  border-bottom-right-radius: 12rpx;
}
.bubble.assistant {
  background: #fffaf3;
  color: #25211c;
  border: 1rpx solid rgba(231, 223, 212, 0.85);
  border-bottom-left-radius: 12rpx;
}
@keyframes bubble-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
.hint {
  padding: 8rpx 32rpx;
  font-size: 22rpx;
  color: #9a9186;
}
.composer {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 18rpx 28rpx 40rpx;
  background: transparent;
}
.input {
  flex: 1;
  background: rgba(255, 252, 246, 0.95);
  border-radius: 999rpx;
  padding: 16rpx 28rpx;
  font-size: 28rpx;
  border: 1rpx solid rgba(231, 223, 212, 0.95);
}
.send {
  margin: 0;
  padding: 0 32rpx;
  line-height: 64rpx;
  background: #2f604f;
  color: #fffaf3;
  border-radius: 999rpx;
  font-weight: 600;
}
.privacy-overlay {
  position: fixed;
  left: 0;
  right: 0;
  top: 0;
  bottom: 0;
  background: rgba(36, 33, 28, 0.42);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48rpx;
}
.privacy-card {
  background: #fffaf3;
  border-radius: 28rpx;
  padding: 36rpx;
  width: 100%;
}
.privacy-title {
  font-size: 32rpx;
  font-weight: 700;
  color: #24211c;
  margin-bottom: 16rpx;
}
.privacy-desc,
.privacy-hint {
  font-size: 26rpx;
  color: #6f665b;
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
