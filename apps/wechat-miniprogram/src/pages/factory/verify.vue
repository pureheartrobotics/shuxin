<template>
  <view class="page">
    <view class="hero">
      <view class="eyebrow">FACTORY QA</view>
      <view class="title">工厂验收</view>
      <view class="subtitle">扫描外壳二维码，验证设备三码一致性。</view>
    </view>

    <view class="panel">
      <view class="label">外壳认领码</view>
      <input
        class="input"
        v-model="claimCode"
        placeholder="扫码后自动填入"
        :disabled="loading"
      />
      <view class="actions">
        <button class="ghost" :disabled="loading" @tap="scanCode">相机扫码</button>
        <button class="primary" :disabled="loading || !claimCode" @tap="runVerify">
          {{ loading ? "验收中…" : "开始验收" }}
        </button>
      </view>
      <view v-if="loading" class="loading-bar">
        <view class="loading-dot" />
        <view class="loading-dot" />
        <view class="loading-dot" />
      </view>
    </view>

    <!-- 验收结果卡片 -->
    <view v-if="result" class="result-card" :class="result.result === 'PASS' ? 'pass' : 'fail'">
      <view class="result-icon">{{ result.result === 'PASS' ? '✓' : '✗' }}</view>
      <view class="result-label">{{ result.result === 'PASS' ? 'PASS 验收通过' : 'FAIL 验收失败' }}</view>
      <view v-if="result.device_id" class="result-detail">设备码: {{ result.device_id }}</view>
      <view v-if="result.mbti" class="mbti-card">
        <view class="mbti-hint">请核对包装盒内人格卡片是否一致</view>
        <view class="mbti-badge">{{ result.mbti.mbti }} · {{ result.mbti.display_name }}</view>
        <view v-if="result.mbti.tagline" class="mbti-tagline">{{ result.mbti.tagline }}</view>
      </view>
      <view v-else-if="result.warnings?.includes('mbti_missing')" class="mbti-warn">
        云端未配置 MBTI，请检查制码记录
      </view>
      <view v-if="result.reason" class="result-reason">{{ reasonText(result.reason) }}</view>
      <view v-if="result.verify_id" class="result-meta">验收 ID: {{ result.verify_id }}</view>
      <button class="ghost continue-btn" @tap="resetVerify">继续验收下一台</button>
    </view>

    <!-- 验收历史 -->
    <view class="section-header">
      <view class="section-title">本次验收记录</view>
      <button class="mini" @tap="loadLogs">刷新</button>
    </view>
    <view v-if="logs.length === 0" class="empty">暂无记录</view>
    <view
      v-for="log in logs"
      :key="log.verify_id"
      class="log-item"
      :class="log.result === 'PASS' ? 'log-pass' : 'log-fail'"
    >
      <view class="log-code">{{ log.claim_code }}</view>
      <view class="log-device">{{ log.device_id }}</view>
      <view v-if="logMbtiLabel(log)" class="log-mbti">{{ logMbtiLabel(log) }}</view>
      <view class="log-badge">{{ log.result }}</view>
      <view v-if="log.fail_reason" class="log-reason">{{ log.fail_reason }}</view>
      <view class="log-time">{{ formatTime(log.verified_at) }}</view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue";
import { onLoad } from "@dcloudio/uni-app";

const apiBase = import.meta.env.VITE_SHUXIN_API_BASE || "http://localhost:8765";
const FACTORY_QA_DENIED = "无工厂验收权限，请联系管理员";

const claimCode = ref("");
const loading = ref(false);
const result = ref<Record<string, any> | null>(null);
const logs = ref<any[]>([]);

onLoad(async () => {
  const token = sessionToken();
  if (!token) {
    uni.redirectTo({ url: "/pages/login/login" });
    return;
  }
  const allowed = await ensureFactoryAccess(token);
  if (!allowed) return;
  loadLogs();
});

async function ensureFactoryAccess(token: string): Promise<boolean> {
  try {
    const res = await new Promise<any>((resolve, reject) => {
      uni.request({
        url: `${apiBase}/api/users/me`,
        method: "POST",
        data: { session_token: token },
        success: (r) => {
          if (r.statusCode >= 200 && r.statusCode < 300) resolve(r.data);
          else reject(new Error((r.data as any)?.error || `HTTP ${r.statusCode}`));
        },
        fail: (e) => reject(new Error(e.errMsg || "请求失败")),
      });
    });
    if (!res.roles?.factory_qa) {
      await new Promise<void>((resolve) => {
        uni.showModal({
          title: "无权限",
          content: FACTORY_QA_DENIED,
          showCancel: false,
          success: () => resolve(),
        });
      });
      uni.navigateBack({ delta: 1 });
      return false;
    }
    return true;
  } catch {
    uni.showToast({ title: FACTORY_QA_DENIED, icon: "none" });
    setTimeout(() => uni.navigateBack({ delta: 1 }), 800);
    return false;
  }
}

function formatFactoryError(message: string): string {
  const text = String(message || "");
  if (text.includes("factory_role")) return FACTORY_QA_DENIED;
  return text || "验收请求失败";
}

function sessionToken(): string {
  const token = String(uni.getStorageSync("shuxin_session_token") || "");
  const expiresAt = String(uni.getStorageSync("shuxin_session_expires_at") || "");
  if (!token) return "";
  if (expiresAt && Date.parse(expiresAt) <= Date.now()) return "";
  return token;
}

function reasonText(reason: string): string {
  const map: Record<string, string> = {
    device_offline: "设备未在线，请检查设备是否开机并联网",
    ack_timeout: "设备响应超时（10s），请重试",
    claim_code_not_found: "认领码不存在或设备已禁用",
    verify_in_progress: "该设备正在验收中，请稍后重试",
    send_failed: "下发指令失败，请检查网络连接",
  };
  return map[reason] || reason;
}

function formatTime(iso: string): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("zh-CN", {
      timeZone: "Asia/Shanghai",
      hour12: false,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

function logMbtiLabel(log: any): string {
  const mbti = String(log?.meta?.mbti || "").trim();
  if (!mbti) return "";
  return mbti;
}

function scanCode() {
  uni.scanCode({
    onlyFromCamera: true,
    scanType: ["barCode", "qrCode"],
    success: (res) => {
      const raw = String(res.result || res.path || "").trim();
      const claimMatch = raw.match(/[?&]claim_code=([^&]+)/);
      claimCode.value = claimMatch ? decodeURIComponent(claimMatch[1]) : raw;
    },
    fail: (err) => {
      uni.showToast({ title: err.errMsg || "扫码失败", icon: "none" });
    },
  });
}

async function runVerify() {
  const code = claimCode.value.trim();
  if (!code) {
    uni.showToast({ title: "请先扫码", icon: "none" });
    return;
  }
  const token = sessionToken();
  if (!token) {
    uni.redirectTo({ url: "/pages/login/login" });
    return;
  }
  loading.value = true;
  result.value = null;
  try {
    const res = await new Promise<any>((resolve, reject) => {
      uni.request({
        url: `${apiBase}/api/factory/verify`,
        method: "POST",
        data: { session_token: token, claim_code: code },
        success: (r) => {
          if (r.statusCode >= 200 && r.statusCode < 300) resolve(r.data);
          else reject(new Error((r.data as any)?.error || `HTTP ${r.statusCode}`));
        },
        fail: (e) => reject(new Error(e.errMsg || "请求失败")),
      });
    });
    result.value = res;
    if (res.result === "PASS") {
      uni.vibrateShort({ type: "medium" });
    } else {
      uni.vibrateShort({ type: "heavy" });
    }
    await loadLogs();
  } catch (err: any) {
    uni.showToast({ title: formatFactoryError(err.message), icon: "none" });
  } finally {
    loading.value = false;
  }
}

function resetVerify() {
  claimCode.value = "";
  result.value = null;
}

async function loadLogs() {
  const token = sessionToken();
  if (!token) return;
  try {
    const res = await new Promise<any>((resolve, reject) => {
      uni.request({
        url: `${apiBase}/api/factory/verify/logs?limit=20`,
        method: "GET",
        header: { "X-Session-Token": token },
        success: (r) => {
          if (r.statusCode >= 200 && r.statusCode < 300) resolve(r.data);
          else reject(new Error(`HTTP ${r.statusCode}`));
        },
        fail: (e) => reject(new Error(e.errMsg || "请求失败")),
      });
    });
    logs.value = (res as any).items || [];
  } catch {
    // 静默失败，不影响主流程
  }
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 48rpx 34rpx 96rpx;
  background:
    radial-gradient(circle at 88% 0%, rgba(47, 96, 79, 0.12), transparent 38%),
    linear-gradient(180deg, #f8f1e7 0%, #f4eee8 48%, #ece7df 100%);
}

.hero {
  padding: 28rpx 4rpx 36rpx;
}

.eyebrow {
  color: #2f604f;
  font-size: 22rpx;
  letter-spacing: 2rpx;
  margin-bottom: 14rpx;
}

.title {
  color: #24211c;
  font-size: 54rpx;
  font-weight: 700;
  line-height: 1.12;
}

.subtitle {
  color: #6f665b;
  font-size: 28rpx;
  line-height: 1.6;
  margin-top: 18rpx;
}

.panel {
  background: rgba(255, 252, 246, 0.92);
  border: 1rpx solid rgba(128, 94, 69, 0.16);
  border-radius: 24rpx;
  box-shadow: 0 18rpx 50rpx rgba(70, 48, 32, 0.08);
  padding: 28rpx;
}

.label {
  color: #4a4037;
  font-size: 28rpx;
  font-weight: 700;
}

.input {
  height: 88rpx;
  margin-top: 18rpx;
  padding: 0 24rpx;
  border-radius: 18rpx;
  background: #ffffff;
  color: #25211c;
  font-size: 28rpx;
}

.actions {
  display: flex;
  gap: 18rpx;
  margin-top: 22rpx;
}

button {
  flex: 1;
  height: 84rpx;
  line-height: 84rpx;
  font-size: 26rpx;
}

.primary {
  color: #fff;
  background: #2f604f;
}

.ghost {
  color: #2f604f;
  background: #e4eee8;
}

.loading-bar {
  display: flex;
  justify-content: center;
  gap: 14rpx;
  margin-top: 24rpx;
}

.loading-dot {
  width: 14rpx;
  height: 14rpx;
  border-radius: 50%;
  background: #2f604f;
  opacity: 0.5;
  animation: blink 1.2s infinite;
}

.loading-dot:nth-child(2) { animation-delay: 0.2s; }
.loading-dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes blink {
  0%, 80%, 100% { opacity: 0.2; }
  40% { opacity: 1; }
}

/* 结果卡片 */
.result-card {
  margin-top: 32rpx;
  border-radius: 24rpx;
  padding: 36rpx 28rpx;
  border: 2rpx solid transparent;
}

.result-card.pass {
  background: rgba(210, 238, 225, 0.9);
  border-color: rgba(47, 96, 79, 0.3);
}

.result-card.fail {
  background: rgba(248, 222, 218, 0.9);
  border-color: rgba(158, 59, 53, 0.3);
}

.result-icon {
  font-size: 80rpx;
  font-weight: 700;
  text-align: center;
}

.pass .result-icon { color: #2f604f; }
.fail .result-icon { color: #9e3b35; }

.result-label {
  text-align: center;
  font-size: 36rpx;
  font-weight: 700;
  margin-top: 10rpx;
}

.pass .result-label { color: #2f604f; }
.fail .result-label { color: #9e3b35; }

.result-detail,
.result-meta {
  margin-top: 14rpx;
  font-size: 24rpx;
  color: #4a4037;
  text-align: center;
}

.result-reason {
  margin-top: 14rpx;
  font-size: 26rpx;
  color: #9e3b35;
  text-align: center;
}

.mbti-card {
  margin-top: 24rpx;
  padding: 22rpx 20rpx;
  border-radius: 18rpx;
  background: rgba(255, 255, 255, 0.75);
  text-align: center;
}

.mbti-hint {
  font-size: 24rpx;
  color: #6f665b;
  margin-bottom: 14rpx;
}

.mbti-badge {
  display: inline-flex;
  padding: 10rpx 22rpx;
  border-radius: 999rpx;
  background: rgba(47, 96, 79, 0.14);
  color: #2f604f;
  font-size: 30rpx;
  font-weight: 700;
}

.mbti-tagline {
  margin-top: 14rpx;
  font-size: 24rpx;
  color: #4a4037;
  line-height: 1.5;
}

.mbti-warn {
  margin-top: 18rpx;
  font-size: 24rpx;
  color: #9b6146;
  text-align: center;
}

.continue-btn {
  margin-top: 28rpx;
  width: 100%;
}

/* 历史记录 */
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18rpx;
  margin: 42rpx 4rpx 18rpx;
}

.section-title {
  color: #4a4037;
  font-size: 28rpx;
  font-weight: 700;
}

.mini {
  flex: 0 0 128rpx;
  min-width: 128rpx;
  height: 62rpx;
  line-height: 62rpx;
  color: #2f604f;
  background: #e4eee8;
  font-size: 24rpx;
}

.empty {
  padding: 36rpx 0;
  color: #82786d;
  font-size: 28rpx;
}

.log-item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10rpx;
  padding: 20rpx 24rpx;
  margin-bottom: 12rpx;
  border-radius: 18rpx;
  border: 1rpx solid transparent;
}

.log-pass {
  background: rgba(228, 238, 232, 0.8);
  border-color: rgba(47, 96, 79, 0.2);
}

.log-fail {
  background: rgba(248, 222, 218, 0.7);
  border-color: rgba(158, 59, 53, 0.2);
}

.log-code {
  font-size: 24rpx;
  color: #4a4037;
  font-weight: 600;
  flex: 1 1 60%;
}

.log-device {
  font-size: 22rpx;
  color: #6f665b;
  flex: 1 1 60%;
}

.log-mbti {
  font-size: 22rpx;
  color: #2f604f;
  font-weight: 600;
  flex: 0 0 auto;
}

.log-badge {
  font-size: 22rpx;
  font-weight: 700;
  padding: 4rpx 16rpx;
  border-radius: 999rpx;
}

.log-pass .log-badge {
  color: #2f604f;
  background: rgba(47, 96, 79, 0.15);
}

.log-fail .log-badge {
  color: #9e3b35;
  background: rgba(158, 59, 53, 0.12);
}

.log-reason {
  font-size: 20rpx;
  color: #9e3b35;
  flex: 1 1 100%;
}

.log-time {
  font-size: 20rpx;
  color: #82786d;
  flex: 0 0 auto;
}
</style>
