/** Bluetooth SIG 基 UUID 后缀：0000XXXX-0000-1000-8000-00805F9B34FB */
const BLUETOOTH_BASE_SUFFIX = "00001000800000805f9b34fb";

function stripUuid(uuid: string): string {
  return String(uuid || "").toLowerCase().replace(/-/g, "");
}

/** 提取 16-bit 别名；非标准基 UUID 则返回完整 stripped 串 */
function uuidAlias(uuid: string): string {
  const stripped = stripUuid(uuid);
  if (stripped.length === 4 && /^[0-9a-f]{4}$/.test(stripped)) {
    return stripped;
  }
  if (stripped.length === 32 && stripped.endsWith(BLUETOOTH_BASE_SUFFIX)) {
    return stripped.slice(4, 8);
  }
  return stripped;
}

/** 微信可能返回 FFFF 短格式，ESP-IDF 为 0000FFFF-... 全量 UUID */
export function bluetoothUuidMatches(actual: string, expected: string): boolean {
  const a = stripUuid(actual);
  const b = stripUuid(expected);
  if (a === b) {
    return true;
  }
  return uuidAlias(a) === uuidAlias(b);
}

/** 将标准 UUID 字符串解析为 ESP protocomm 使用的 16 字节序 */
export function parseUuid128(uuid: string): Uint8Array {
  const parts = uuid.toLowerCase().split("-");
  if (parts.length !== 5) {
    throw new Error(`invalid UUID: ${uuid}`);
  }
  const hex = (value: string) => parseInt(value, 16);
  const bytes = new Uint8Array(16);
  const timeLow = hex(parts[0]);
  bytes[15] = timeLow & 0xff;
  bytes[14] = (timeLow >> 8) & 0xff;
  bytes[13] = (timeLow >> 16) & 0xff;
  bytes[12] = (timeLow >> 24) & 0xff;
  const timeMid = hex(parts[1]);
  bytes[11] = timeMid & 0xff;
  bytes[10] = (timeMid >> 8) & 0xff;
  const timeHi = hex(parts[2]);
  bytes[9] = timeHi & 0xff;
  bytes[8] = (timeHi >> 8) & 0xff;
  bytes[7] = hex(parts[3].slice(0, 2));
  bytes[6] = hex(parts[3].slice(2, 4));
  for (let i = 0; i < 6; i += 1) {
    bytes[5 - i] = hex(parts[4].slice(i * 2, i * 2 + 2));
  }
  return bytes;
}

/** 将 ESP protocomm 16 字节序格式化为标准 UUID 字符串 */
export function formatUuid128(bytes: Uint8Array): string {
  const hex = (value: number) => value.toString(16).padStart(2, "0");
  const timeLow =
    (bytes[12] << 24) | (bytes[13] << 16) | (bytes[14] << 8) | bytes[15];
  const timeMid = (bytes[10] << 8) | bytes[11];
  const timeHi = (bytes[8] << 8) | bytes[9];
  const clock = `${hex(bytes[7])}${hex(bytes[6])}`;
  const node = [5, 4, 3, 2, 1, 0].map((index) => hex(bytes[index])).join("");
  return `${timeLow.toString(16).padStart(8, "0")}-${timeMid
    .toString(16)
    .padStart(4, "0")}-${timeHi.toString(16).padStart(4, "0")}-${clock}-${node}`.toUpperCase();
}

/**
 * 按 ESP-IDF protocomm_ble 规则：复制 service UUID，覆写 byte[0..1] 为 endpoint 短 ID（小端）
 *
 * BLE UUID 以小端存储，byte[0] = UUID 字符串末尾 2 个十六进制字符，byte[1] = 倒数第 2 组。
 * 因此正确的派生结果是 UUID 字符串末尾 4 个十六进制字符被替换：
 *   Service:    1775244D-6B43-439B-877C-060F2D9BED07
 *   prov-session(ff51): 1775244D-6B43-439B-877C-060F2D9BFF51  ← 末尾变，前面不变
 *
 * 旧实现错误地修改了 bytes[12..13]（对应 UUID 字符串开头），产生了错误的 UUID。
 */
export function deriveEndpointCharacteristicUuid(serviceUuid: string, shortUuid16: number): string {
  const bytes = parseUuid128(serviceUuid);
  bytes[14] = (shortUuid16 >> 8) & 0xff;
  bytes[15] = shortUuid16 & 0xff;
  return formatUuid128(bytes);
}
