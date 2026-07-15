# 微信小程序 — 易错清单（Pitfalls）

**受众**：小程序 / 固件 / 提审运营  
**更新**：2026-07-14  
**权威对照代码**：`apps/wechat-miniprogram/`  
更完整流程见 [`WECHAT_MINIPROGRAM.md`](WECHAT_MINIPROGRAM.md)、[`WECHAT_BLE_PROVISIONING_HANDOFF.md`](WECHAT_BLE_PROVISIONING_HANDOFF.md)。

改代码前先扫一遍「做错会怎样」；Obsidian 镜像：`knowledge/shuxin/微信小程序/易错清单.md`。

---

## 1. 构建与预览

| 做错 | 正确 |
|------|------|
| 微信工具导入源码目录直接改 | `bash scripts/wechat_miniprogram_dev.sh build` 后导入 `dist/dev/mp-weixin` 或 `dist/build/mp-weixin` |
| build 后不重编 / 不清缓存 | DevTools：**清缓存 → 重新编译 → 真机预览** |
| 用 `import()` 动态加载 ESP-IDF 客户端 | 顶层 `import`；模块放 `pages/prov/esp-idf-prov/`（勿放 `utils/`） |
| `check_page_outputs` 仍要求 `pages/mall/index` | 量产已关商城主包页；校验列表不含 mall |

---

## 2. 量产入口（勿当已删代码）

| 项 | 现状 | 勿做 |
|----|------|------|
| TabBar | 仅 **设备 \| 我的** | 不要假定还有「商城」Tab |
| 商城 | `modules/mall` + `/api/mall/*` **保留**；主包/Tab/个人中心入口关闭 | 勿直接删 `modules/mall` |
| 配网调试面板 | `SHOW_PROVISION_DEV_LOGS = false`（`ble.vue`） | 排障时改 `true`，量产勿默认打开 |

恢复路径见 [`WECHAT_MINIPROGRAM.md`](WECHAT_MINIPROGRAM.md) §6、[`MALL_MODULE_ARCHITECTURE.md`](MALL_MODULE_ARCHITECTURE.md)。

---

## 3. 隐私与审核

| 做错 | 正确 |
|------|------|
| 位置用途写成「获取用户当前位置信息」 | Android **BLE 扫描**所需系统权限；**不**调用 `wx.getLocation`，不采集 GPS。可粘贴文案见 [`WECHAT_MINIPROGRAM.md`](WECHAT_MINIPROGRAM.md) §5 |
| `manifest` `scope.userLocation.desc` 写「搜索 Wi-Fi」 | 仅写：在 Android 上搜索附近蓝牙设备以完成配网 |
| 蓝牙写进 `requiredPrivateInfos` | **禁止**（该字段仅地理位置类） |
| `requirePrivacyAuthorize` + `agreePrivacyAuthorization` 叠用 | 只用后者；`privacy.ts` 方案 A |
| 登录页默认勾选协议 | **禁止**；须用户主动勾选 |
| 后台勾选手机 Wi-Fi 接口 | 勿勾；SSID 来自设备 `prov-scan` |
| `privacy.vue` 与公众平台后台文案不一致 | 两边必须一致后再提审 |

---

## 4. BLE 配网协议

| 做错 | 正确 |
|------|------|
| 旧 FFFF / FFF1 / FFF2 JSON 协议 | ESP-IDF `wifi_prov_scheme_ble` + Security1；Service UUID `1775244D-...` |
| PoP 用广播名 | 量产 PoP 固定 **`shuxin`**；广播名 = 设备码，仅扫描/绑定预填 |
| 乐鑫文档 UUID 表硬套本机 | 量产短 UUID：`prov-scan=ff50`、`prov-session=ff51`、`prov-config=ff52`、`proto-ver=ff53`（见 handoff） |
| 用手机 `getWifiList` 扫 Wi-Fi | 设备端 `prov-scan`；iOS 上 `getWifiList` 体验差且易断 BLE |
| Step2 `onHide` 关掉 BLE | Step≥2 须**保留会话**（用户切设置页常见） |
| 扫描不过滤 | 量产 `BLE_FILTER_SX_PREFIX_ONLY=true`；仅 `sx` 前缀广播名 |

---

## 5. GetStatus / 首次配网「密码错误」

现象：第一次报「Wi-Fi 密码错误」，同密码重新配网成功。

| 做错 | 正确 |
|------|------|
| `fail_reason ?? 0` → 当成 AuthError | field 10 **未出现在 wire 上**时 **禁止**判 `failed_auth`，继续轮询 |
| 忽略 field 12 `attempt_failed` | `attempts_remaining > 0` → 视为 **connecting** |
| 第一次终态失败就 throw | 连续 **2** 次终态失败才报错；首次 poll 建议延迟 3s |
| 无回归测试就改解析 | `node tests/test_wifi_config_proto.mjs` |

实现：`wifi-config-proto.ts`、`provision-client.ts`；说明：handoff §6。

---

## 6. Android 定位权限

- 仅 Android 在扫 BLE 前 `authorize("scope.userLocation")`
- 系统定位开关未开 → 扫不到设备（不是「小程序坏了」）
- 不读、不上传坐标

---

## 7. 速查命令

```bash
bash scripts/wechat_miniprogram_dev.sh build
node tests/test_wifi_config_proto.mjs
node tests/test_wifi_scan_proto.mjs
python -m pytest tests/test_wechat_miniprogram_scaffold.py -q
```
