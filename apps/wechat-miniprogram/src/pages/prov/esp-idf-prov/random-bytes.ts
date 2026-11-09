/** 生成 32 字节 CSPRNG，供 Security1 X25519 密钥对种子使用 */

export function randomBytes32(): Uint8Array {
  const buf = new Uint8Array(32);
  const crypto = typeof globalThis !== "undefined"
    ? (globalThis as { crypto?: Crypto }).crypto
    : undefined;
  if (crypto?.getRandomValues) {
    crypto.getRandomValues(buf);
    return buf;
  }
  for (let i = 0; i < buf.length; i += 1) {
    buf[i] = Math.floor(Math.random() * 256);
  }
  return buf;
}
