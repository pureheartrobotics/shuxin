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
# 设置您的微信小程序 AppID（或直接运行，默认使用游客模式 touristappid）
export WECHAT_MINIPROGRAM_APPID="your-appid"

# 启动开发编译监听
../../scripts/wechat_miniprogram_dev.sh
```

- **编译产物路径**：`apps/wechat-miniprogram/dist/dev/mp-weixin`
- **后台地址绑定**：脚本默认会将小程序的后端 API 地址设为 `http://localhost:8765`。如果要手动指定后端地址，可设置环境变量 `SHUXIN_API_BASE`，例如：
  ```bash
  SHUXIN_API_BASE=https://your-domain.com ../../scripts/wechat_miniprogram_dev.sh
  ```

### 3. 导入微信开发者工具

1. 打开**微信开发者工具**，选择导入项目。
2. **非常重要**：**导入的目录必须是编译产物目录，不能是源码目录！**
   - 开发调试时，导入目录选择：`apps/wechat-miniprogram/dist/dev/mp-weixin`
3. 填写您的 AppID（需与步骤 2 中设置 of AppID 一致，或者使用测试号）。
4. 导入成功后，在微信开发者工具中进行如下设置：
   - 点击右上角 **详情** -> **本地设置** -> 勾选 **「不校验合法域名、web-view（业务域名）、TLS版本以及HTTPS证书」**。

---

## 📦 生产环境打包

如果需要打包生成用于发布的生产版本，请运行生产构建脚本：

```bash
# 生产构建
../../scripts/wechat_miniprogram_build.sh
```

- **构建产物路径**：`apps/wechat-miniprogram/dist/build/mp-weixin`
- 微信开发者工具中，将项目目录切换为该路径即可进行预览或上传审核。

---

## 🔌 联调与测试技巧

### 1. 微信登录模拟 (Mock Mode)
小程序登录需要通过微信官方接口 `code2Session` 换取 `openid`。
如果您在本地没有配置真实的微信小程序 `AppID` 和 `AppSecret`，可在**后端服务**的 `.env` 配置文件中设置：
```env
SHUXIN_WECHAT_MOCK=1
```
开启 Mock 模式后，后端会自动模拟登录过程，并使用 mock 的 openid 注册和登录，免去繁琐的微信服务接口校验。

### 2. 工厂 QA 验收测试
对于工厂验收和 QA 测试流程：
1. 后端接口可生成三码：外壳条形码 `claim_code`、内部 `device_id` 和一次性密钥 `device_secret`。
2. 将测试账号的角色设为 `roles.factory_qa`（可在管理员后台 `/admin` 的用户管理中勾选“工厂 QA”权限）。
3. 微信小程序登录该账号后，个人中心会出现「工厂验收」入口，支持直接扫码验收设备。
