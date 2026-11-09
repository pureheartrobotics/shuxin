const PENDING_KEY = "shuxin_pending_designation";
const NAME_KEY = "shuxin_user_name";
const DESIGNATION_KEY = "shuxin_robot_designation";
const DONE_KEY = "shuxin_first_meet_done";

/** Shown when the simulator opens with no camera scan and no saved code. */
export const SIMULATOR_DESIGNATION = "CX-001";

function readRaw(key: string): string {
  return String(uni.getStorageSync(key) || "").trim();
}

export function isFirstMeetComplete(): boolean {
  return readRaw(DONE_KEY) === "1" && readRaw(NAME_KEY).length > 0 && readRaw(DESIGNATION_KEY).length > 0;
}

export function storedUserName(): string {
  return readRaw(NAME_KEY);
}

export function storedDesignation(): string {
  return readRaw(DESIGNATION_KEY);
}

export function extractDesignation(value: unknown): string {
  let raw = String(value ?? "").trim();
  if (!raw) return "";
  try {
    raw = decodeURIComponent(raw.replace(/\+/g, " "));
  } catch {
    /* keep the original text */
  }
  const deviceMatch = raw.match(/[?&]device_code=([^&#\s]+)/i);
  const claimMatch = raw.match(/[?&]claim_code=([^&#\s]+)/i);
  let code = deviceMatch?.[1] || claimMatch?.[1] || "";
  if (!code && !raw.includes("://") && !raw.startsWith("/") && !raw.includes(" ")) {
    code = raw.replace(/^device_code=/i, "").replace(/^claim_code=/i, "");
  }
  if (!code) return "";
  try {
    code = decodeURIComponent(code);
  } catch {
    /* keep the matched text */
  }
  code = code.trim();
  if (!code || code.length > 64 || /[\r\n\t]/.test(code)) return "";
  return code;
}

export function captureLaunchQuery(query: Record<string, unknown> | undefined | null) {
  if (!query) return;
  const candidates = [query.device_code, query.claim_code, query.q, query.scene];
  for (const item of candidates) {
    const code = extractDesignation(item);
    if (code) {
      uni.setStorageSync(PENDING_KEY, code);
      return;
    }
  }
}

export function captureEnterOptions() {
  try {
    const current = typeof uni.getEnterOptionsSync === "function" ? uni.getEnterOptionsSync() : undefined;
    captureLaunchQuery(current?.query as Record<string, unknown> | undefined);
  } catch {
    /* launch options are absent in some tool previews */
  }
  try {
    const launch = typeof uni.getLaunchOptionsSync === "function" ? uni.getLaunchOptionsSync() : undefined;
    captureLaunchQuery(launch?.query as Record<string, unknown> | undefined);
  } catch {
    /* ignore */
  }
}

export function resolveDesignation(): string {
  const pending = readRaw(PENDING_KEY);
  if (pending) return pending;
  const temp = extractDesignation(readRaw("temp_device_code"));
  if (temp) return temp;
  const saved = readRaw(DESIGNATION_KEY);
  if (saved) return saved;
  return SIMULATOR_DESIGNATION;
}

export function completeFirstMeet(name: string, designation: string) {
  const trimmedName = name.trim();
  const code = designation.trim() || SIMULATOR_DESIGNATION;
  uni.setStorageSync(NAME_KEY, trimmedName);
  uni.setStorageSync(DESIGNATION_KEY, code);
  uni.setStorageSync(DONE_KEY, "1");
  uni.removeStorageSync(PENDING_KEY);
}
