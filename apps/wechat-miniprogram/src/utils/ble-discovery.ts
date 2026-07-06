/** BLE 扫描过滤与设备名解析（对齐微信官方 bluetooth 示例） */

export const PROVISION_SERVICE_UUID = "0000FFFF-0000-1000-8000-00805F9B34FB";

/** 单次扫描最长持续时间（毫秒） */
export const BLE_SCAN_DURATION_MS = 12000;

/** 配网广播名前缀（小写比较，大小写不敏感） */
export const BLE_NAME_PREFIXES = ["sx"];

type BleAdvertisedDevice = {
  name?: string;
  localName?: string;
  deviceId?: string;
  RSSI?: number;
};

/** 设备广播出来的可读名称（无则返回空字符串） */
export function getBleAdvertisedName(device: BleAdvertisedDevice): string {
  return String(device.name || device.localName || "").trim();
}

function matchesAllowedPrefix(name: string): boolean {
  const lower = name.toLowerCase();
  return BLE_NAME_PREFIXES.some((prefix) => lower.startsWith(prefix));
}

/** 有名且广播名以 SX 开头（不区分大小写） */
export function shouldIncludeBleDevice(device: BleAdvertisedDevice): boolean {
  const name = getBleAdvertisedName(device);
  if (!name) {
    return false;
  }
  return matchesAllowedPrefix(name);
}

export function isChuxinDeviceName(name: string): boolean {
  const trimmed = name.trim();
  if (!trimmed) {
    return false;
  }
  const lower = trimmed.toLowerCase();
  return lower.startsWith("sx") || trimmed.includes("初心") || trimmed.includes("稚子心");
}

/** 广播名即设备码：通过过滤则原样返回，不做格式转换 */
export function extractDeviceCodeFromBleName(name: string): string {
  const trimmed = String(name || "").trim();
  if (!trimmed || !shouldIncludeBleDevice({ name: trimmed })) {
    return "";
  }
  return trimmed;
}

export function sortDiscoveredDevices<T extends { name: string; RSSI: number }>(devices: T[]): T[] {
  return [...devices].sort((a, b) => (b.RSSI ?? -100) - (a.RSSI ?? -100));
}
