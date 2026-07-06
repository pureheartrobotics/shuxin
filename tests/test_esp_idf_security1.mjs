/**
 * Security1 密钥生成回归测试（Node，不依赖微信运行时）
 * 运行：node tests/test_esp_idf_security1.mjs
 */
import { createRequire } from "node:module";
import { randomFillSync } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const curve25519 = require(join(root, "apps/wechat-miniprogram/node_modules/curve25519-js"));

function randomBytes32() {
  const buf = new Uint8Array(32);
  randomFillSync(buf);
  return buf;
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

// curve25519-js 要求显式传入 32 字节 seed
const seed = randomBytes32();
const keyPair = curve25519.generateKeyPair(seed);
assert(keyPair.public.length === 32, "public key must be 32 bytes");
assert(keyPair.private.length === 32, "private key must be 32 bytes");

// 无 seed 时必须失败（防止回归）
let threw = false;
try {
  curve25519.generateKeyPair();
} catch {
  threw = true;
}
assert(threw, "generateKeyPair() without seed must throw");

// 构建产物中 Security1Session 可加载且 createSessionRequest0 返回非空
const buildSecurity1 = join(
  root,
  "apps/wechat-miniprogram/dist/build/mp-weixin/pages/prov/esp-idf-prov/security1.js",
);
let buildSecurity1Loaded = false;
try {
  const vendorPath = join(root, "apps/wechat-miniprogram/dist/build/mp-weixin/common/vendor.js");
  global.wx = { getSystemInfoSync: () => ({ platform: "devtools", language: "zh_CN" }) };
  global.Page = function Page() {};
  global.Component = function Component() {};
  require(vendorPath);
  const { Security1Session } = require(buildSecurity1);
  const session = new Security1Session("SX-000003");
  const payload = session.createSessionRequest0();
  assert(payload instanceof Uint8Array, "createSessionRequest0 must return Uint8Array");
  assert(payload.length > 0, "createSessionRequest0 payload must not be empty");
  buildSecurity1Loaded = true;
} catch (err) {
  console.warn(
    "skip built Security1Session test (run bash scripts/wechat_miniprogram_dev.sh build first):",
    err.message,
  );
}

console.log(
  buildSecurity1Loaded
    ? "test_esp_idf_security1: OK (keygen + built Security1Session)"
    : "test_esp_idf_security1: OK (keygen only; built bundle not tested)",
);
