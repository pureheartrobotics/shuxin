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
    <scroll-view
      scroll-y
      class="msgs"
      :style="{ height: msgsHeight + 'px' }"
      :scroll-into-view="scrollId"
      scroll-with-animation
    >
      <view v-if="!messages.length" class="empty-hint">
        <text>和 {{ name }} 的对话会像微信一样保存在这里</text>
      </view>
      <view
        v-for="(m, i) in messages"
        :key="'m' + i + '-' + m.role"
        :id="'m' + i"
        class="bubble-row"
        :class="m.role"
      >
        <view v-if="(m.text || '').trim()" class="bubble" :class="m.role">
          <text selectable>{{ m.text }}</text>
        </view>
      </view>
      <view id="m-bottom" class="scroll-anchor" />
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
        :disabled="quotaBlocked || busy || !chatReady"
        @confirm="sendText"
      />
      <button
        class="send"
        size="mini"
        :disabled="busy || quotaBlocked || !chatReady"
        @tap="sendText"
      >
        发送
      </button>
    </view>
    <view v-if="quotaBlocked" class="paywall">
      <text>陪伴点已用尽，充值后继续聊</text>
      <button size="mini" class="pay-btn" @tap="goRecharge">去充值</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { nextTick, onUnmounted, ref } from "vue";
import { onLoad, onReady } from "@dcloudio/uni-app";
import { ApiError } from "../../core/http";
import {
  ackCare,
  chatText,
  chatTextStream,
  fetchChatHistory,
  fetchEngagement,
  fetchUserMe,
  softCredentials,
} from "../../modules/companions/api";
import { SoftVoiceSession } from "../../modules/companions/voice-ws";
import { stripActionParens } from "../../modules/companions/voice-ws-decode";
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
import { isAgeAgreed, markAgeAgreed } from "../../utils/policy";

/** 语音气泡累计 raw，展示时再 strip，避免流式半括弧闪一下 */
let voiceAssistantRaw = "";

const companionId = ref("");
const mbti = ref("");
const name = ref("");
const draft = ref("");
const messages = ref<{ role: string; text: string }[]>([]);
const scrollId = ref("m-bottom");
const msgsHeight = ref(400);
const chatReady = ref(false);
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
const ageBlocked = ref(false);

let voice: SoftVoiceSession | null = null;
let softCreds: { device_id: string; device_secret: string } | null = null;
let pendingEnterVoice = false;
let streamAssistantIndex = -1;
let voiceUserBubbleIndex = -1;
let voiceAssistantIndex = -1;
let scrollTimer: ReturnType<typeof setTimeout> | null = null;

function estimateMsgsHeight() {
  try {
    const sys = uni.getSystemInfoSync();
    const bottom = Number(sys.safeAreaInsets?.bottom || 0);
    // header + composer + hint 粗估，真机再 selector 精修
    msgsHeight.value = Math.max(220, Math.floor(sys.windowHeight - 230 - bottom));
  } catch {
    msgsHeight.value = 400;
  }
}

function layoutMsgsHeight() {
  estimateMsgsHeight();
  nextTick(() => {
    const q = uni.createSelectorQuery();
    q.select(".header").boundingClientRect();
    q.select(".care-banner").boundingClientRect();
    q.select(".hint").boundingClientRect();
    q.select(".nudge").boundingClientRect();
    q.select(".composer").boundingClientRect();
    q.select(".paywall").boundingClientRect();
    q.exec((rects: any[]) => {
      let used = 0;
      for (const r of rects || []) {
        if (r && typeof r.height === "number") used += r.height;
      }
      try {
        const sys = uni.getSystemInfoSync();
        msgsHeight.value = Math.max(220, Math.floor(sys.windowHeight - used));
      } catch {
        /* keep estimate */
      }
    });
  });
}

function scrollToBottom(force = false) {
  const go = () => {
    scrollId.value = "";
    setTimeout(() => {
      scrollId.value = "m-bottom";
    }, 16);
  };
  if (force) {
    go();
    return;
  }
  if (scrollTimer) clearTimeout(scrollTimer);
  scrollTimer = setTimeout(go, 80);
}

function isQuotaExhaustedMessage(raw: string) {
  return (
    raw.includes("quota_exhausted") ||
    raw.includes("额度已用尽") ||
    raw.includes("陪伴点已用尽")
  );
}

function pushMessage(role: string, text: string) {
  messages.value.push({ role, text });
  return messages.value.length - 1;
}

function appendToMessage(index: number, text: string) {
  if (index < 0 || index >= messages.value.length) return;
  const cur = messages.value[index];
  messages.value.splice(index, 1, { role: cur.role, text: cur.text + text });
}

function setMessage(index: number, text: string) {
  if (index < 0 || index >= messages.value.length) return;
  const cur = messages.value[index];
  messages.value.splice(index, 1, { role: cur.role, text });
}

function redirectToAgeGate() {
  ageBlocked.value = true;
  const ret = encodeURIComponent(
    `/pages/chat/chat?companion_id=${encodeURIComponent(companionId.value)}&mbti=${encodeURIComponent(mbti.value)}&name=${encodeURIComponent(name.value)}`
  );
  uni.redirectTo({ url: `/pages/legal/age?return_url=${ret}` });
}

async function ensureAgeConsent(): Promise<boolean> {
  if (isAgeAgreed()) {
    return true;
  }
  try {
    const me: any = await fetchUserMe();
    if (me?.age_consent?.agreed) {
      markAgeAgreed();
      return true;
    }
  } catch {
    /* fall through to gate */
  }
  redirectToAgeGate();
  return false;
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

onReady(() => {
  layoutMsgsHeight();
});

onLoad(async (query: any) => {
  companionId.value = decodeURIComponent(query?.companion_id || "");
  mbti.value = decodeURIComponent(query?.mbti || "");
  name.value = decodeURIComponent(query?.name || "伙伴");
  statusHint.value = "文字聊天可直接发送";
  estimateMsgsHeight();
  privacyContractName.value = await loadPrivacyContractName();
  setPrivacyGateHandler(async () => {
    showPrivacyGate.value = true;
  });
  const okAge = await ensureAgeConsent();
  if (!okAge) {
    return;
  }
  try {
    const hist: any = await fetchChatHistory(companionId.value, 50);
    const items = Array.isArray(hist?.messages) ? hist.messages : [];
    // 仅在本地尚无消息时灌入历史，避免覆盖用户已发送的气泡
    if (messages.value.length === 0) {
      messages.value = items
        .filter((m: any) => m && (m.role === "user" || m.role === "assistant") && String(m.text || "").trim())
        .map((m: any) => ({ role: String(m.role), text: String(m.text) }));
      scrollToBottom(true);
    }
  } catch {
    /* history optional on first open */
  }
  chatReady.value = true;
  layoutMsgsHeight();
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
  layoutMsgsHeight();
});

onUnmounted(() => {
  setPrivacyGateHandler(null);
  voice?.close();
  voice = null;
});

function sendText() {
  const text = draft.value.trim();
  if (
    !text ||
    !companionId.value ||
    !chatReady.value ||
    busy.value ||
    quotaBlocked.value ||
    ageBlocked.value ||
    mode.value !== "text"
  ) {
    return;
  }
  pushMessage("user", text);
  draft.value = "";
  busy.value = true;
  statusHint.value = "回复中…";
  // 首个 delta / 最终 reply 再插入 assistant，避免空气泡导致真机滚动/裁切异常
  streamAssistantIndex = -1;
  scrollToBottom(true);
  layoutMsgsHeight();

  const finishOk = (res: any) => {
    const reply = String(res.reply || "…");
    if (streamAssistantIndex < 0) {
      streamAssistantIndex = pushMessage("assistant", reply);
    } else if (!(messages.value[streamAssistantIndex]?.text || "").trim()) {
      setMessage(streamAssistantIndex, reply);
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
    scrollToBottom(true);
    layoutMsgsHeight();
  };

  const fail = (e: any) => {
    if (e instanceof ApiError && (e.code === "age_consent_required" || e.body?.error === "age_consent_required")) {
      redirectToAgeGate();
      busy.value = false;
      streamAssistantIndex = -1;
      return;
    }
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
    scrollToBottom(true);
  };

  chatTextStream(companionId.value, text, {
    onDelta: (piece) => {
      if (streamAssistantIndex < 0) {
        streamAssistantIndex = pushMessage("assistant", piece);
      } else {
        appendToMessage(streamAssistantIndex, piece);
      }
      scrollToBottom();
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
  if (quotaBlocked.value || busy.value || mode.value === "voice" || ageBlocked.value) return;
  if (!(await ensureAgeConsent())) return;
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
  voiceAssistantRaw = "";
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
        voiceAssistantRaw = "";
      }
    },
    onThinking: () => {
      statusHint.value = "思考中…";
      busy.value = true;
    },
    onDelta: (piece) => {
      voiceAssistantRaw += String(piece || "");
      const visible = stripActionParens(voiceAssistantRaw);
      if (!visible) return;
      if (voiceAssistantIndex < 0) {
        voiceAssistantIndex = pushMessage("assistant", visible);
      } else {
        setMessage(voiceAssistantIndex, visible);
      }
    },
    onReply: (text) => {
      voiceAssistantRaw = String(text || "");
      const visible = stripActionParens(voiceAssistantRaw).trim();
      const body = visible || "（没有听清文字，请再说一次）";
      if (voiceAssistantIndex < 0) {
        voiceAssistantIndex = pushMessage("assistant", body);
      } else {
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
      } else if (
        raw.includes("tts_failed") ||
        raw.includes("tts_audio_missing") ||
        raw.includes("tts_write_failed") ||
        raw.includes("语音合成") ||
        raw.includes("播放失败")
      ) {
        // 保留诊断明细（chunks/errMsg），便于真机对照
        statusHint.value = mapped
          ? mapped.message
          : raw.includes("tts_audio_missing")
            ? `语音播放失败（无音频包）`
            : raw.includes("tts_write_failed")
              ? `语音写盘失败`
              : raw.includes("播放失败")
                ? raw
                : raw.includes("语音合成")
                  ? raw
                  : "语音播放失败";
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
    // 双保险：connect 内已 setupRecorder；若 onReady 早于 recorder 竞态被 pending 吃掉，这里再开麦
    voice.startListen();
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
  voiceAssistantRaw = "";
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
  height: 100vh;
  overflow: hidden;
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
  flex-shrink: 0;
  padding: 20rpx 28rpx;
  box-sizing: border-box;
  width: 100%;
}
.empty-hint {
  padding: 48rpx 24rpx;
  text-align: center;
  font-size: 26rpx;
  color: #9a9186;
  line-height: 1.5;
}
.bubble-row {
  display: flex;
  margin-bottom: 22rpx;
}
.bubble-row.user {
  justify-content: flex-end;
}
.bubble-row.assistant {
  justify-content: flex-start;
}
.bubble {
  max-width: 78%;
  padding: 22rpx 28rpx;
  border-radius: 28rpx;
  font-size: 30rpx;
  line-height: 1.55;
  word-break: break-word;
  animation: bubble-in 0.28s ease-out;
}
.bubble.user {
  background: linear-gradient(145deg, #3d7a64 0%, #2f604f 100%);
  color: #fffaf3;
  border-bottom-right-radius: 10rpx;
  box-shadow: 0 6rpx 18rpx rgba(47, 96, 79, 0.18);
}
.bubble.assistant {
  background: #fffaf3;
  color: #25211c;
  border: 1rpx solid rgba(210, 200, 186, 0.9);
  border-bottom-left-radius: 10rpx;
  box-shadow: 0 4rpx 14rpx rgba(74, 58, 40, 0.05);
}
.scroll-anchor {
  height: 2rpx;
}
@keyframes bubble-in {
  from {
    opacity: 0;
    transform: translateY(8rpx);
  }
  to {
    opacity: 1;
    transform: translateY(0);
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
  padding: 18rpx 28rpx calc(24rpx + env(safe-area-inset-bottom));
  background: rgba(247, 244, 239, 0.94);
  border-top: 1rpx solid rgba(231, 223, 212, 0.85);
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
