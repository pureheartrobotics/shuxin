/** BLE 权限预检与微信蓝牙错误映射（小程序蓝牙配网） */

import { assertBlePrivacyAuthorized, mapWxPrivacyApiError } from "./privacy";

export type BleErrorCode =
  | "DEVTOOLS_UNSUPPORTED"
  | "LOCATION_DENIED"
  | "BLUETOOTH_OFF"
  | "BLUETOOTH_UNAUTHORIZED"
  | "ADAPTER_OPEN_FAILED"
  | "DISCOVERY_FAILED";

export class BleReadyError extends Error {
  readonly code: BleErrorCode;
  readonly errMsg?: string;
  readonly wxErrCode?: number;

  constructor(code: BleErrorCode, message: string, errMsg?: string, wxErrCode?: number) {
    super(message);
    this.name = "BleReadyError";
    this.code = code;
    this.errMsg = errMsg;
    this.wxErrCode = wxErrCode;
  }
}

function isDevtools(): boolean {
  try {
    const info = uni.getSystemInfoSync();
    return info.platform === "devtools";
  } catch {
    return false;
  }
}

function isAndroid(): boolean {
  try {
    const info = uni.getSystemInfoSync();
    return String(info.platform).toLowerCase() === "android";
  } catch {
    return false;
  }
}

function isIOS(): boolean {
  try {
    const info = uni.getSystemInfoSync();
    return String(info.platform).toLowerCase() === "ios";
  } catch {
    return false;
  }
}

function isPrivacyRelatedErrMsg(errMsg: string): boolean {
  const lower = errMsg.toLowerCase();
  return (
    lower.includes("privacy") ||
    lower.includes("not authorized") ||
    lower.includes("api banned") ||
    lower.includes("auth deny") ||
    lower.includes("permission denied") ||
    lower.includes("未授权") ||
    lower.includes("隐私")
  );
}

function promisify<T>(fn: (opts: UniNamespace.OpenBluetoothAdapterOptions) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    fn({
      success: (res) => resolve(res as T),
      fail: (err) => reject(err),
    });
  });
}

function getSetting(): Promise<UniNamespace.GetSettingSuccessResult> {
  return promisify((opts) => uni.getSetting(opts));
}

function authorize(scope: string): Promise<void> {
  return promisify((opts) => uni.authorize({ ...opts, scope }));
}

function openSetting(): Promise<UniNamespace.OpenSettingSuccessResult> {
  return promisify((opts) => uni.openSetting(opts));
}

function getBluetoothAdapterState(): Promise<UniNamespace.GetBluetoothAdapterStateSuccess> {
  return promisify((opts) => uni.getBluetoothAdapterState(opts));
}

function closeBluetoothAdapter(): Promise<void> {
  return new Promise((resolve) => {
    uni.closeBluetoothAdapter({
      success: () => resolve(),
      fail: () => resolve(),
    });
  });
}

function openBluetoothAdapter(): Promise<void> {
  return new Promise((resolve, reject) => {
    uni.openBluetoothAdapter({
      success: () => resolve(),
      fail: (err) => reject(err),
    });
  });
}

async function ensureLocationPermission(): Promise<void> {
  if (!isAndroid()) {
    return;
  }

  const setting = await getSetting();
  if (setting.authSetting["scope.userLocation"]) {
    return;
  }

  try {
    await authorize("scope.userLocation");
    return;
  } catch {
    // fall through to settings prompt
  }

  const reopened = await new Promise<boolean>((resolve) => {
    uni.showModal({
      title: "需要定位权限",
      content: "Android 搜索蓝牙设备需要开启定位权限，请在设置中允许「初心」使用位置信息。",
      confirmText: "去设置",
      success: async (res) => {
        if (!res.confirm) {
          resolve(false);
          return;
        }
        try {
          const next = await openSetting();
          resolve(Boolean(next.authSetting["scope.userLocation"]));
        } catch {
          resolve(false);
        }
      },
      fail: () => resolve(false),
    });
  });

  if (!reopened) {
    throw new BleReadyError(
      "LOCATION_DENIED",
      "需要定位权限才能搜索蓝牙设备（Android）。请在微信设置中允许位置信息。",
    );
  }
}

function mapWxAdapterError(err: UniNamespace.GeneralCallbackResult): BleReadyError {
  const wxErrCode = (err as { errCode?: number }).errCode;
  const errMsg = (err.errMsg || "").toLowerCase();

  if (errMsg.includes("privacy api banned") || errMsg.includes("未声明")) {
    return new BleReadyError(
      "ADAPTER_OPEN_FAILED",
      "微信公众平台需在「用户隐私保护指引」中声明蓝牙，并重新上传体验版后再预览。",
      err.errMsg,
      wxErrCode,
    );
  }
  const mappedPrivacy = mapWxPrivacyApiError(err.errMsg || "");
  if (mappedPrivacy || isPrivacyRelatedErrMsg(errMsg)) {
    return new BleReadyError(
      "ADAPTER_OPEN_FAILED",
      mappedPrivacy?.message || "请先点击「同意并继续」完成隐私授权后再扫描。",
      err.errMsg,
      wxErrCode,
    );
  }
  if (errMsg.includes("already opened")) {
    return new BleReadyError(
      "ADAPTER_OPEN_FAILED",
      "蓝牙适配器已开启，请重试扫描。",
      err.errMsg,
      wxErrCode,
    );
  }
  if (wxErrCode === 10001) {
    return new BleReadyError(
      "BLUETOOTH_OFF",
      "手机蓝牙未开启，请在系统设置中打开蓝牙后重试。",
      err.errMsg,
      wxErrCode,
    );
  }
  if (wxErrCode === 10004) {
    return new BleReadyError(
      "BLUETOOTH_UNAUTHORIZED",
      "微信未获得蓝牙权限，请在手机设置中允许微信使用蓝牙。",
      err.errMsg,
      wxErrCode,
    );
  }

  if (isIOS()) {
    return new BleReadyError(
      "ADAPTER_OPEN_FAILED",
      "请先点击同意隐私保护指引后再扫描；若仍失败，请检查微信公众平台是否已声明蓝牙接口。",
      err.errMsg,
      wxErrCode,
    );
  }

  return new BleReadyError(
    "ADAPTER_OPEN_FAILED",
    "无法初始化蓝牙，请确认手机蓝牙已开启且授权给微信。",
    err.errMsg,
    wxErrCode,
  );
}

/** adapter 失败且应回退展示隐私弹窗（方案 A 的 reactive 兜底） */
export function shouldShowPrivacyGateForBleError(err: unknown): boolean {
  if (!(err instanceof BleReadyError) || err.code !== "ADAPTER_OPEN_FAILED") {
    return false;
  }
  if (err.errMsg && isPrivacyRelatedErrMsg(err.errMsg)) {
    return true;
  }
  return isIOS();
}

async function ensureBluetoothAdapterOpen(): Promise<void> {
  try {
    const state = await getBluetoothAdapterState();
    if (state.available) {
      return;
    }
    throw new BleReadyError(
      "BLUETOOTH_OFF",
      "手机蓝牙未开启，请在系统设置中打开蓝牙后重试。",
    );
  } catch (err) {
    if (err instanceof BleReadyError) {
      throw err;
    }
    // adapter 未打开时继续尝试 open
  }

  try {
    await openBluetoothAdapter();
  } catch (err) {
    const errMsg = String((err as UniNamespace.GeneralCallbackResult)?.errMsg || "").toLowerCase();
    if (errMsg.includes("already opened")) {
      return;
    }
    throw mapWxAdapterError(err as UniNamespace.GeneralCallbackResult);
  }
}

export type EnsureBleReadyOptions = {
  /** agreePrivacyAuthorization 回调后跳过 getPrivacySetting 复查 */
  skipPrivacyCheck?: boolean;
};

/** 扫描前确保环境满足 BLE 初始化条件（含隐私授权） */
export async function ensureBleReady(options: EnsureBleReadyOptions = {}): Promise<void> {
  if (isDevtools()) {
    throw new BleReadyError(
      "DEVTOOLS_UNSUPPORTED",
      "微信开发者工具不支持蓝牙配网，请使用「预览」扫码或「真机调试」在手机上测试。",
    );
  }

  if (!options.skipPrivacyCheck) {
    await assertBlePrivacyAuthorized();
  }
  await ensureLocationPermission();
  await ensureBluetoothAdapterOpen();
}

/** 页面卸载时关闭蓝牙适配器 */
export async function closeBleAdapter(): Promise<void> {
  await closeBluetoothAdapter();
}

let discoveryStarted = false;

export function markBluetoothDiscoveryStopped(): void {
  discoveryStarted = false;
}

export function stopBluetoothDiscovery(): Promise<void> {
  markBluetoothDiscoveryStopped();
  return new Promise((resolve) => {
    uni.stopBluetoothDevicesDiscovery({
      success: () => resolve(),
      fail: () => resolve(),
    });
  });
}

export function startBluetoothDiscovery(): Promise<void> {
  if (discoveryStarted) {
    return Promise.resolve();
  }
  return new Promise((resolve, reject) => {
    uni.startBluetoothDevicesDiscovery({
      allowDuplicatesKey: false,
      success: () => {
        discoveryStarted = true;
        resolve();
      },
      fail: (err) => {
        reject(
          new BleReadyError(
            "DISCOVERY_FAILED",
            `开启蓝牙搜索失败: ${err.errMsg || "未知错误"}`,
            err.errMsg,
            (err as { errCode?: number }).errCode,
          ),
        );
      },
    });
  });
}

export function mapBleError(err: unknown): string {
  if (err instanceof BleReadyError) {
    return err.message;
  }
  if (err && typeof err === "object" && "errMsg" in err) {
    return `操作失败: ${String((err as { errMsg?: string }).errMsg)}`;
  }
  return "蓝牙操作失败，请稍后重试。";
}

export function getBleDebugDetail(err: unknown): string {
  if (err instanceof BleReadyError) {
    const parts = [err.code];
    if (err.wxErrCode !== undefined) {
      parts.push(`wx:${err.wxErrCode}`);
    }
    if (err.errMsg) {
      parts.push(err.errMsg);
    }
    return parts.join(" | ");
  }
  if (err && typeof err === "object" && "errMsg" in err) {
    return String((err as { errMsg?: string }).errMsg);
  }
  return "";
}
