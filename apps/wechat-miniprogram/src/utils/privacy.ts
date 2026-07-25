/**
 * 微信小程序隐私合规（蓝牙配网）
 * 以 getPrivacySetting + agreePrivacyAuthorization 为主路径；
 * onNeedPrivacyAuthorization 仅作被动兜底。
 */

export const PRIVACY_AGREE_BUTTON_ID = "ble-privacy-agree-btn";
/** 聊天页按住说话隐私同意按钮 id（须与 open-type=agreePrivacyAuthorization 的 button id 一致） */
export const CHAT_PRIVACY_AGREE_BUTTON_ID = "chat-privacy-agree-btn";

export class PrivacyNeedAgreeError extends Error {
  readonly privacyContractName: string;

  constructor(privacyContractName: string) {
    super("需要用户同意隐私保护指引");
    this.name = "PrivacyNeedAgreeError";
    this.privacyContractName = privacyContractName;
  }
}

export class PrivacyDeniedError extends Error {
  constructor(message = "您已拒绝隐私授权，无法继续") {
    super(message);
    this.name = "PrivacyDeniedError";
  }
}

export class PrivacyBackendError extends Error {
  constructor(
    message = "微信公众平台需在「用户隐私保护指引」中声明所用接口（蓝牙 / 麦克风录音等），并重新上传体验版后再预览。",
  ) {
    super(message);
    this.name = "PrivacyBackendError";
  }
}

export type BlePrivacyStatus = {
  needed: boolean;
  contractName: string;
};

type PrivacySettingResult = {
  needAuthorization: boolean;
  privacyContractName: string;
};

type NeedPrivacyResolve = (result: { event: "agree" | "disagree"; buttonId?: string }) => void;

let needPrivacyHandler: (() => void | Promise<void>) | null = null;
let pendingNeedPrivacyResolves: NeedPrivacyResolve[] = [];

function getWx(): any {
  return (globalThis as any).wx;
}

function supportsPrivacyApi(): boolean {
  const wxApi = getWx();
  return Boolean(wxApi && typeof wxApi.getPrivacySetting === "function");
}

function isBackendPrivacyError(errMsg: string): boolean {
  const lower = errMsg.toLowerCase();
  return (
    lower.includes("api banned") ||
    lower.includes("未声明") ||
    lower.includes("not declared") ||
    lower.includes("privacy api") ||
    lower.includes("scope is not declared")
  );
}

function getPrivacySetting(): Promise<PrivacySettingResult> {
  return new Promise((resolve, reject) => {
    const wxApi = getWx();
    if (!wxApi || typeof wxApi.getPrivacySetting !== "function") {
      resolve({ needAuthorization: false, privacyContractName: "" });
      return;
    }
    wxApi.getPrivacySetting({
      success: (res: PrivacySettingResult) => resolve(res),
      fail: (err: { errMsg?: string }) => reject(err),
    });
  });
}

/** 查询微信侧是否仍需用户同意隐私指引（蓝牙等隐私接口前置检查） */
export async function checkBlePrivacyNeeded(): Promise<BlePrivacyStatus> {
  if (!supportsPrivacyApi()) {
    return { needed: false, contractName: "" };
  }
  try {
    const setting = await getPrivacySetting();
    return {
      needed: Boolean(setting.needAuthorization),
      contractName: setting.privacyContractName || "《用户隐私保护指引》",
    };
  } catch {
    return { needed: false, contractName: "《用户隐私保护指引》" };
  }
}

/** 录音 / 麦克风与蓝牙共用同一套微信隐私授权状态查询 */
export const checkRecordPrivacyNeeded = checkBlePrivacyNeeded;

export async function assertRecordPrivacyAuthorized(): Promise<void> {
  const { needed, contractName } = await checkRecordPrivacyNeeded();
  if (needed) {
    throw new PrivacyNeedAgreeError(contractName);
  }
}

export async function loadPrivacyContractName(): Promise<string> {
  const status = await checkBlePrivacyNeeded();
  return status.contractName || "《用户隐私保护指引》";
}

/** 调用隐私接口前断言用户已在微信侧完成授权，否则抛 PrivacyNeedAgreeError */
export async function assertBlePrivacyAuthorized(): Promise<void> {
  const { needed, contractName } = await checkBlePrivacyNeeded();
  if (needed) {
    throw new PrivacyNeedAgreeError(contractName);
  }
}

export function mapWxPrivacyApiError(errMsg: string): Error | null {
  if (!errMsg) {
    return null;
  }
  if (isBackendPrivacyError(errMsg)) {
    return new PrivacyBackendError();
  }
  if (
    errMsg.toLowerCase().includes("privacy") ||
    errMsg.includes("未同意") ||
    errMsg.includes("拒绝")
  ) {
    return new PrivacyDeniedError();
  }
  return null;
}

export function openPrivacyContract(): Promise<void> {
  return new Promise((resolve, reject) => {
    const wxApi = getWx();
    if (!wxApi || typeof wxApi.openPrivacyContract !== "function") {
      reject(new Error("当前环境不支持打开隐私指引"));
      return;
    }
    wxApi.openPrivacyContract({
      success: () => resolve(),
      fail: (err: { errMsg?: string }) => reject(err),
    });
  });
}

/** 注册页面侧隐私弹窗展示回调（由 ble.vue 等调用） */
export function setPrivacyGateHandler(handler: (() => void | Promise<void>) | null): void {
  needPrivacyHandler = handler;
}

/**
 * App 启动时注册：被动监听隐私接口授权需求（兜底，避免微信弹官方窗）。
 */
export function registerPrivacyAuthorizationHandler(): void {
  const wxApi = getWx();
  if (!wxApi || typeof wxApi.onNeedPrivacyAuthorization !== "function") {
    return;
  }
  wxApi.onNeedPrivacyAuthorization((resolve: NeedPrivacyResolve) => {
    pendingNeedPrivacyResolves.push(resolve);
    if (needPrivacyHandler) {
      void Promise.resolve(needPrivacyHandler());
    }
  });
}

function flushPrivacyResolves(
  result: { event: "agree" | "disagree"; buttonId?: string },
): void {
  const batch = pendingNeedPrivacyResolves;
  pendingNeedPrivacyResolves = [];
  batch.forEach((resolve) => resolve(result));
}

/**
 * 在 bindagreeprivacyauthorization 回调内调用。
 * buttonId 须与 agreePrivacyAuthorization 按钮 id 一致。
 */
export function notifyPrivacyAgreed(buttonId: string = PRIVACY_AGREE_BUTTON_ID): void {
  flushPrivacyResolves({ event: "agree", buttonId });
}

/** 用户拒绝隐私授权（自定义弹窗「暂不同意」） */
export function notifyPrivacyDenied(): void {
  flushPrivacyResolves({ event: "disagree" });
}

export function mapPrivacyError(err: unknown): string {
  if (err instanceof PrivacyBackendError) {
    return err.message;
  }
  if (err instanceof PrivacyDeniedError) {
    return err.message;
  }
  if (err instanceof PrivacyNeedAgreeError) {
    return "请先阅读并同意隐私保护指引后再继续";
  }
  return "";
}
