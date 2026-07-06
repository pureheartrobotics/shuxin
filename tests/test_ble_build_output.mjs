/**
 * 蓝牙配网页构建产物回归（mp-weixin 禁止 broken dynamic import）
 * 运行：node tests/test_ble_build_output.mjs
 */
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const bleJs = join(root, "apps/wechat-miniprogram/dist/dev/mp-weixin/pages/prov/ble.js");
const provisionClientJs = join(
  root,
  "apps/wechat-miniprogram/dist/dev/mp-weixin/pages/prov/esp-idf-prov/provision-client.js",
);

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

assert(existsSync(bleJs), `missing ${bleJs} — run bash scripts/wechat_miniprogram_dev.sh build first`);
assert(
  existsSync(provisionClientJs),
  `missing ${provisionClientJs} — esp-idf-prov must be emitted under pages/prov/`,
);

const source = readFileSync(bleJs, "utf8");

assert(
  !source.includes('await"../../utils/esp-idf-prov') && !source.includes('await"./esp-idf-prov'),
  "ble.js must not contain broken dynamic import for esp-idf-prov",
);

assert(
  source.includes("EspIdfProvisionClient") || source.includes("esp-idf-prov"),
  "ble.js must reference esp-idf-prov provision client",
);

console.log("test_ble_build_output: OK");
