/** Wi-Fi 扫描调试：hex 格式化（真机日志用） */

export function bytesToHex(buffer: Uint8Array, maxLen = 64): string {
  if (!buffer || buffer.length === 0) {
    return "(empty)";
  }
  const slice = buffer.slice(0, maxLen);
  const hex = Array.from(slice)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  if (buffer.length > maxLen) {
    return `${hex}…(+${buffer.length - maxLen}B)`;
  }
  return hex;
}

export function formatBlePayloadLog(label: string, raw: Uint8Array, decrypted?: Uint8Array): string {
  const parts = [`${label} rawLen=${raw.length} rawHex=${bytesToHex(raw)}`];
  if (decrypted) {
    parts.push(`decryptedLen=${decrypted.length} decryptedHex=${bytesToHex(decrypted)}`);
  }
  return parts.join(" ");
}

/** proto-ver 端点返回明文 JSON（如 {"prov":{...}}），误入扫描解析时提前识别 */
export function looksLikeProtoVerJson(raw: Uint8Array): boolean {
  if (!raw || raw.length === 0) {
    return false;
  }
  const head = raw.slice(0, Math.min(raw.length, 32));
  const text = String.fromCharCode(...head).trimStart();
  return text.startsWith("{") && text.includes("prov");
}
