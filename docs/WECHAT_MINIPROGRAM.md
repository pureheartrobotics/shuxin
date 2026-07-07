# 微信小程序 — 接入、合规与蓝牙配网

**受众**：小程序开发者、提审运营、固件联调  
**代码目录**：`apps/wechat-miniprogram/`  
**开发指南**（编译、Mock、工厂 QA）：[`apps/wechat-miniprogram/README.md`](../apps/wechat-miniprogram/README.md)

---

## 1. 构建与导入

改源码后必须重新编译，微信开发者工具导入**产物目录**，不是源码：

```bash
bash scripts/wechat_miniprogram_dev.sh build   # 生产包 → dist/build，并同步到 dist/dev
bash scripts/wechat_miniprogram_dev.sh         # 开发监听 → dist/dev/mp-weixin
```

微信开发者工具可导入 **`apps/wechat-miniprogram`**、**`dist/dev/mp-weixin`** 或 **`dist/build/mp-weixin`**。`build` 脚本从 `src/manifest.example.json` 生成 `manifest.json`，并 patch 根目录与产物内 `project.config.json` 的 AppID（默认读根目录 `.env` 的 `SHUXIN_WECHAT_APPID`）。执行 `build` 后脚本会把最新产物同步到 `dev`，避免「已 build 但工具仍加载旧包」导致白屏。

**mp-weixin 限制**：勿使用 ES `import()` 延迟加载（会编译成 `await "path"`，Android 真机报 `e is not a constructor`）。ESP-IDF 客户端须放在 [`pages/prov/esp-idf-prov/`](../apps/wechat-miniprogram/src/pages/prov/esp-idf-prov/)（页面同级，勿放 `utils/`），在 [`ble.vue`](../apps/wechat-miniprogram/src/pages/prov/ble.vue) 顶层 `import from "./esp-idf-prov"`。`build` 后须在 DevTools **清缓存 → 重新编译 → 重新真机预览**。

---

## 2. 登录页隐私合规（应用层协议）

**审核要求**：不得默认勾选同意；须用户主动勾选后才能登录。

| 模块 | 路径 | 职责 |
|------|------|------|
| 协议页 | `pages/legal/terms.vue`、`pages/legal/privacy.vue` | 《用户服务协议》《隐私政策》正文 |
| 同意状态 | `utils/policy.ts` | `POLICY_VERSION`、`isPolicyAgreed()`、`markPolicyAgreed()` |
| 登录门控 | `pages/login/login.vue` | 未勾选时按钮禁用；链到协议页 |
| 个人中心 | `pages/profile/profile.vue` | 协议入口 |

版本 bump 时更新 `POLICY_VERSION`，旧用户须重新勾选。

---

## 3. 蓝牙配网 — 微信隐私 API

**页面**：`pages/prov/ble.vue`  
**工具**：`utils/privacy.ts`、`utils/ble-permissions.ts`

### 正确路径

1. `getPrivacySetting` 判断是否需要授权  
2. 需要时展示自定义门控，用户点「同意并继续」→ `agreePrivacyAuthorization`（`open-type="agreePrivacyAuthorization"`）  
3. `onNeedPrivacyAuthorization` 仅作被动兜底，须正确 `resolve` 队列  

### 禁止

- 与 `requirePrivacyAuthorize` 叠用（会导致官方弹窗「同意」无效）  
- 在 `app.json` 的 `requiredPrivateInfos` 写蓝牙（该字段仅支持地理位置类）

### Android 额外权限

扫描 BLE 需 `manifest.json` 声明 `scope.userLocation`，并在运行时引导用户授权。**不采集 GPS 坐标**，仅为系统扫描蓝牙所必需。

---

## 4. BLE 扫描与 ESP-IDF 配网

**扫描过滤**：[`utils/ble-discovery.ts`](../apps/wechat-miniprogram/src/utils/ble-discovery.ts) — 仅 `sx` 前缀、广播名即设备码。

**配网协议**：[`pages/prov/esp-idf-prov/`](../apps/wechat-miniprogram/src/pages/prov/esp-idf-prov/) — ESP-IDF `wifi_prov_scheme_ble` + Security1（v5 默认 Service UUID `1775244D-...`）。

| 规则 | 说明 |
|------|------|
| 扫描过滤 | `BLE_NAME_PREFIXES = ["sx"]`（大小写不敏感） |
| PoP | 固定 `shuxin`（与当前量产固件一致）；广播名仅用于扫描与绑定预填 |
| 预填 | 配网成功后广播名原样写入绑定页 |
| 协议 | `prov-session` 握手 + `prov-config` 下发 Wi-Fi（Protobuf，非 JSON） |

**硬件对接详表**：[`docs/WECHAT_BLE_PROVISIONING_HANDOFF.md`](WECHAT_BLE_PROVISIONING_HANDOFF.md)

---

## 5. 微信公众平台「用户隐私保护指引」文案

代码内 [`privacy.vue`](../apps/wechat-miniprogram/src/pages/legal/privacy.vue) 与后台指引须一致。提审驳回常见原因：用途描述与接口场景不符。

| 信息类型 | 推荐用途说明 |
|----------|--------------|
| **蓝牙** | 通过低功耗蓝牙（BLE）连接处于配网模式的设备，并向设备发送 Wi-Fi 账号密码以完成网络配置 |
| **位置信息** | 在 Android 系统上扫描附近蓝牙设备需申请位置权限；本小程序不采集、不上传 GPS 坐标 |
| **Wi-Fi** | 读取当前连接的 Wi-Fi 名称（SSID），用于向设备发送 2.4GHz 配网信息 |
| **摄像头** | 扫描设备外壳条形码以识别设备码并完成绑定 |

后台勾选：**蓝牙**、**Wi-Fi**（若使用）、**摄像头**（扫码绑定）、**位置信息**（Android BLE 扫描）。提审「用户隐私收集」与后台一致。

---

## 6. 真机验收清单

1. 登录页：未勾选时无法登录；勾选后可登录；协议页可打开  
2. 蓝牙配网：隐私门控「同意并继续」后可扫描；12s 自动停扫  
3. 列表仅出现广播名以 `SX` 开头（大小写不限）的设备  
4. 点击设备后 ESP-IDF Security1 握手（PoP=`shuxin`）→ 填 Wi-Fi → 配网成功 → 绑定页预填设备码  

---

## 7. 关键文件索引

```
apps/wechat-miniprogram/src/
├── pages/login/login.vue       # 登录 + 协议勾选
├── pages/legal/                # 协议正文
├── pages/prov/ble.vue          # 蓝牙配网 UI + 扫描
│   └── esp-idf-prov/           # ESP-IDF protocomm 配网客户端（页面同级）
├── utils/policy.ts             # 应用层协议同意
├── utils/privacy.ts            # 微信隐私 API
├── utils/ble-discovery.ts      # 扫描过滤（sx 前缀）
└── utils/ble-permissions.ts    # 蓝牙/定位权限 + discovery 生命周期
```
