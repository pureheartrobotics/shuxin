# 📱 初心 (ChuXin) 微信小程序开发指南

本项目是**初心 (ChuXin) 陪伴型 AI 智能体**的配套微信小程序，用于实现设备绑定、MBTI 盲盒揭晓、设备列表展示，以及工厂 QA 扫码验收等功能。

---

## 🛠️ 开发前准备

在开始开发或运行小程序之前，请确保您的本地开发环境已安装以下工具：

1. **Node.js** (建议使用 v18 或更高版本)
2. **pnpm** 包管理器（如未安装，可通过 `npm install -g pnpm` 安装）
3. **微信开发者工具**（用于导入和调试编译后的小程序产物）

---

## 🚀 快速开始

### 1. 安装依赖

在 `apps/wechat-miniprogram` 目录下执行以下命令安装依赖：

```bash
cd apps/wechat-miniprogram
pnpm install
```

### 2. 启动开发模式（热重载）

使用开发模式运行，系统会监听源码变化并实时重新编译。

运行以下命令（如果在 WSL 环境下，脚本会自动获取宿主机 IP 地址进行 API 绑定）：

```bash
# AppID 解析顺序：WECHAT_MINIPROGRAM_APPID 环境变量 → 根目录 .env 的 SHUXIN_WECHAT_APPID → 默认 wxda3acb8842b5c9f4
# 可选覆盖：export WECHAT_MINIPROGRAM_APPID="your-appid"

# 启动开发编译监听
../../scripts/wechat_miniprogram_dev.sh
```

- **编译产物路径**：`apps/wechat-miniprogram/dist/dev/mp-weixin`
- **导入微信开发者工具**：可导入 **`apps/wechat-miniprogram`**（含 `project.config.json`），也可直接导入 **`dist/dev/mp-weixin`** 或 **`dist/build/mp-weixin`**；脚本会从 `manifest.example.json` 生成 `manifest.json`，并在 build 后 patch 产物内 `project.config.json` 的 AppID
- **后台地址绑定**：脚本默认 API 为 `https://shuxinzzx.com.cn`。覆盖示例：
  ```bash
  SHUXIN_API_BASE=https://your-domain.com ../../scripts/wechat_miniprogram_dev.sh
  ```

### 3. 导入微信开发者工具

1. 打开**微信开发者工具**，选择导入项目。
2. **导入目录**：`apps/wechat-miniprogram`、`dist/dev/mp-weixin` 或 `dist/build/mp-weixin` 均可（须先执行下方 build/dev 脚本，AppID 由脚本注入，勿手动填 `touristappid`）。
3. 若项目详情仍显示旧 AppID：删除工具内旧项目后重新导入。
4. 导入成功后，在微信开发者工具中进行如下设置：
   - 点击右上角 **详情** -> **本地设置** -> 勾选 **「不校验合法域名、web-view（业务域名）、TLS版本以及HTTPS证书」**。

---

## 📦 生产环境打包

如果需要打包生成用于发布的生产版本，请运行生产构建脚本：

```bash
# 生产构建（产物写入 dist/build，并自动同步到 dist/dev 供 DevTools 使用）
bash scripts/wechat_miniprogram_dev.sh build
```

- **构建产物路径**：`apps/wechat-miniprogram/dist/build/mp-weixin`
- **`build` 后会自动同步到 `dist/dev/mp-weixin`**，与 `project.config.json` 的 `miniprogramRoot` 一致；改源码后须重新 build 并在工具内点「编译」

---

## 📋 合规与架构（必读）

登录隐私、BLE 授权、扫描过滤、微信后台「用户隐私保护指引」文案、固件广播名约定见项目根文档：

**[`docs/WECHAT_MINIPROGRAM.md`](../../docs/WECHAT_MINIPROGRAM.md)** · 硬件对接：**[`docs/WECHAT_BLE_PROVISIONING_HANDOFF.md`](../../docs/WECHAT_BLE_PROVISIONING_HANDOFF.md)**

---

## 🔌 联调与测试技巧

### 1. 登录页协议勾选

登录须用户**主动勾选**《用户服务协议》和《隐私政策》（`utils/policy.ts`），未勾选时登录按钮禁用。提审勿默认勾选。

### 2. 微信登录模拟 (Mock Mode)
小程序登录需要通过微信官方接口 `code2Session` 换取 `openid`。
如果您在本地没有配置真实的微信小程序 `AppID` 和 `AppSecret`，可在**后端服务**的 `.env` 配置文件中设置：
```env
SHUXIN_WECHAT_MOCK=1
```
开启 Mock 模式后，后端会自动模拟登录过程，并使用 mock 的 openid 注册和登录，免去繁琐的微信服务接口校验。

### 3. 工厂 QA 验收测试
对于工厂验收和 QA 测试流程：
1. 后端接口可生成三码：外壳条形码 `claim_code`、内部 `device_id` 和一次性密钥 `device_secret`。
2. 将测试账号的角色设为 `roles.factory_qa`（可在管理员后台 `/admin` 的用户管理中勾选“工厂 QA”权限）。
3. 微信小程序登录该账号后，个人中心会出现「工厂验收」入口，支持直接扫码验收设备。

### 4. 蓝牙配网真机测试

蓝牙配网页面（`pages/prov/ble`）**不能在微信开发者工具模拟器中完成 BLE 初始化**，必须使用真机：

1. 重新编译小程序：`../../scripts/wechat_miniprogram_dev.sh`
2. 微信开发者工具 → **预览**（扫码）或 **真机调试**
3. 手机侧准备：
   - 打开系统蓝牙
   - Android：同时打开**定位**开关，并在微信中允许「位置信息」
   - 设备进入配网模式（指示灯快闪）
4. 首次扫描会先弹出**隐私保护提示**，点击「同意并继续」后再搜索蓝牙
5. 绑定页 →「新设备未联网？立即进行蓝牙配网」→ 开始扫描 → 列表**仅显示广播名以 SX 开头的设备** → 点击设备（PoP 自动取广播名）→ 填写 2.4GHz Wi-Fi → 发送配置
6. 配网成功后返回绑定页；广播名（= 设备码）自动预填

**微信小程序后台**（代码 + 后台双侧缺一不可）：

- 「设置 → 服务内容声明 → 用户隐私保护指引」中勾选 **蓝牙**（使用 Wi-Fi 扫描时还需勾选 Wi-Fi 相关信息）
- 提审时「用户隐私收集」须与后台指引一致
- 蓝牙**不要**写入 `app.json` 的 `requiredPrivateInfos`（该字段仅支持地理位置类接口）
- Android 扫描 BLE 还需 `manifest.json` 中 `permission.scope.userLocation` 并引导用户授权
