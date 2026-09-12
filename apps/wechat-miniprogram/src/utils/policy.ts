/** 应用层《用户服务协议》+《隐私政策》同意状态（与微信隐私 API 层 privacy.ts 分离） */

export const POLICY_VERSION = "2026-07-03";

const AGREED_AT_KEY = "shuxin_policy_agreed_at";
const VERSION_KEY = "shuxin_policy_version";

export function isPolicyAgreed(): boolean {
  const agreedAt = String(uni.getStorageSync(AGREED_AT_KEY) || "");
  const version = String(uni.getStorageSync(VERSION_KEY) || "");
  if (!agreedAt) {
    return false;
  }
  return version === POLICY_VERSION;
}

export function markPolicyAgreed(): void {
  uni.setStorageSync(AGREED_AT_KEY, new Date().toISOString());
  uni.setStorageSync(VERSION_KEY, POLICY_VERSION);
}

export function clearPolicyAgreed(): void {
  uni.removeStorageSync(AGREED_AT_KEY);
  uni.removeStorageSync(VERSION_KEY);
}
