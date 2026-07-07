/** BLE 扫描过滤与设备名解析（对齐微信官方 bluetooth 示例） */

export const PROVISION_SERVICE_UUID = "1775244D-6B43-439B-877C-060F2D9BED07";

/** 调试：false = 展示所有 BLE 设备；量产改回 true */
export const BLE_FILTER_SX_PREFIX_ONLY = false;

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

/** 列表展示名：有广播名用原名，否则用 deviceId 后缀 */
export function getBleDeviceListName(device: BleAdvertisedDevice): string {
  const advertised = getBleAdvertisedName(device);
  if (advertised) {
    return advertised;
  }
  const id = String(device.deviceId || "").trim();
  if (!id) {
    return "未知设备";
  }
  const suffix = id.length > 8 ? id.slice(-8) : id;
  return `未知设备 · ${suffix}`;
}

/** 有名且广播名以 SX 开头（不区分大小写）；调试模式下有 deviceId 即入列表 */
export function shouldIncludeBleDevice(device: BleAdvertisedDevice): boolean {
  if (!BLE_FILTER_SX_PREFIX_ONLY) {
    return Boolean(String(device.deviceId || "").trim());
  }
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
  if (!trimmed) {
    return "";
  }
  if (!BLE_FILTER_SX_PREFIX_ONLY) {
    if (trimmed.startsWith("未知设备")) {
      return "";
    }
    return trimmed;
  }
  if (!shouldIncludeBleDevice({ name: trimmed })) {
    return "";
  }
  return trimmed;
}

export function sortDiscoveredDevices<T extends { name: string; RSSI: number }>(devices: T[]): T[] {
  return [...devices].sort((a, b) => (b.RSSI ?? -100) - (a.RSSI ?? -100));
}
