# 微信支付配置与迁移

舒心小程序充值走 **微信支付 APIv3 · 小程序支付**。本文档覆盖：**证书配置**、**本地 cloudflared 联调**、**生产服务器迁移**。

## 1. 证书与密钥

将商户平台下载的文件放到宿主机（会通过 `./data` 挂载进容器）：

```text
data/certs/
├── apiclient_key.pem            # 商户 API 私钥（apiclient_key.pem）
├── apiclient_cert.pem           # 商户证书（用于读取序列号）
├── wxp_pub.pem                  # 微信支付公钥（新商户必填，见下文）
└── wxpay_platform/              # 旧平台证书模式自动下载目录（新商户可留空）
```

`.env` 示例：

```bash
SHUXIN_WECHAT_MOCK=0
SHUXIN_WECHAT_APPID=你的小程序AppID
SHUXIN_WECHAT_SECRET=你的小程序Secret

SHUXIN_WXPAY_MCHID=你的商户号
SHUXIN_WXPAY_API_V3_KEY=你的APIv3密钥
SHUXIN_WXPAY_CERT_SERIAL_NO=商户证书序列号
SHUXIN_WXPAY_PRIVATE_KEY_PATH=/app/data/certs/apiclient_key.pem
SHUXIN_WXPAY_NOTIFY_URL=https://你的公网HTTPS地址/api/payment/notify

# 新商户（2024+）：使用「微信支付公钥」验签，不再提供平台证书
SHUXIN_WXPAY_PUBLIC_KEY_PATH=/app/data/certs/wxp_pub.pem
SHUXIN_WXPAY_PUBLIC_KEY_ID=PUB_KEY_ID_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 平台证书 vs 微信支付公钥

若下单报错 `No wechatpay platform certificate`，在容器内运行：

```bash
docker exec shuxin-voice-demo-pg python /app/scripts/diagnose_wxpay_certs.py
```

若 `GET /v3/certificates` 返回 `RESOURCE_NOT_EXISTS` / 「无可用的平台证书」，说明商户号已切换到**微信支付公钥模式**：

1. 登录 [微信支付商户平台](https://pay.weixin.qq.com) → **账户中心 → API安全**
2. 申请/下载 **微信支付公钥**（`.pem`），并复制 **公钥 ID**（形如 `PUB_KEY_ID_...`）
3. 将公钥放到 `data/certs/wxp_pub.pem`，在 `.env` 配置 `SHUXIN_WXPAY_PUBLIC_KEY_PATH` 与 `SHUXIN_WXPAY_PUBLIC_KEY_ID`
4. `bash scripts/redeploy_docker.sh --skip-build` 后重试充值

旧商户仍可使用平台证书：留空公钥配置，SDK 会从 `/v3/certificates` 自动下载到 `wxpay_platform/`。

## 2. 充值套餐与到账比例（Admin）

套餐与全局到账比例存 **Postgres**（迁移 `007` + `008_payment_plans_balance_tiers.sql`），在 `/admin` → **充值套餐** Tab 管理：

1. **到账比例** `credit_ratio`（默认 0.95）：用户付 100 元 → 界面余额 +100，DMX 实际 +95。仅影响**新创建**订单；履约使用下单时快照。
2. **固定档位**（默认 10/30/50 元，`amount_fen` 为分：1000/3000/5000）：新增/编辑 `plan_id`、名称、支付价、排序；停用 = 软删。
3. **用户 Tab**：Admin 可见「用户余额 / DMX 额度」；Admin「充值」填**用户可见金额**（与微信支付双账本一致）；小程序 `remain_yuan` 为用户可见余额。
4. **老用户**：首次查 quota 时若 `display_balance_yuan` 为空且 DMX>0，按 DMX 1:1 懒回填（仅一次）。

无 Postgres 时仍可读 `data/payment_plans.json` 或 `SHUXIN_PAYMENT_PLANS` 作 fallback；Admin CRUD 需 `DATABASE_URL`。

| Admin API | 说明 |
|-----------|------|
| `GET/POST/PATCH/DELETE /admin/api/payment/plans` | 套餐 CRUD（DELETE 为软删） |
| `GET/PATCH /admin/api/platform/payment-settings` | 读/改 `credit_ratio` |

新用户注册礼：DMX 与 `display_balance_yuan` 各 +10 元（1:1，不受付费倍率影响）。

### 2.1 旧版 JSON 配置（fallback）

```bash
cp data/payment_plans.example.json data/payment_plans.json
```

或通过 `SHUXIN_PAYMENT_PLANS` 传入 JSON 数组。字段：`id`、`name`、`amount_fen`（`add_yuan` 默认同支付价）。

## 3. 本地 notify_url（cloudflared 推荐）

微信支付回调 **必须是 HTTPS**，不能填 `http://localhost:8765`。

### 一键脚本（推荐）

```bash
# 终端 1：先确保 voice 服务在 8765 运行
bash scripts/redeploy_docker.sh

# 终端 2：启动 cloudflared 并自动写入 .env
bash scripts/start_payment_dev_tunnel.sh
```

脚本会：

1. 启动 `cloudflared tunnel --url http://127.0.0.1:8765`
2. 解析 `https://xxxx.trycloudflare.com` 并写入 `SHUXIN_WXPAY_NOTIFY_URL`（**仅支付回调**，不是小程序 API）
3. 提示 `redeploy`；**不必**因 tunnel 换域名而重编小程序

然后重部署 Docker（让新 notify_url 生效）：

```bash
bash scripts/redeploy_docker.sh --skip-build
```

### DevTools 本地联调（推荐，少操作）

小程序 **request** 固定连 `http://localhost:8765`；**微信支付 notify** 仍走 trycloudflare HTTPS。

| 链路 | 地址 |
|------|------|
| 登录 / 余额 / create-order | `http://localhost:8765`（build 一次） |
| 微信服务器支付回调 | `SHUXIN_WXPAY_NOTIFY_URL` → tunnel → 8765 |

**首次**（或清掉旧 trycloudflare 常量后）编译小程序：

```bash
WECHAT_MINIPROGRAM_APPID=你的AppID bash scripts/wechat_miniprogram_dev.sh build-local
```

微信开发者工具：

1. 打开 `apps/wechat-miniprogram/dist/build/mp-weixin`
2. **详情 → 本地设置 → 勾选「不校验合法域名、web-view、TLS…」**
3. 点 **编译**

**tunnel 重启后**只需：

```bash
bash scripts/start_payment_dev_tunnel.sh
bash scripts/redeploy_docker.sh --skip-build
```

WSL2：若 DevTools 连不上 `localhost:8765`，改用 Windows 能访问的地址一次性 build：

```bash
SHUXIN_API_BASE=http://<WSL或宿主机IP>:8765 bash scripts/wechat_miniprogram_dev.sh build-local
```

### 530 / 仍请求旧 trycloudflare

- 原因：旧 build 把 tunnel 域名写进了 JS；或 tunnel 已停
- 处理：`build-local` 重编 + DevTools 清缓存再编译；login 应指向 `localhost:8765`

### 手动方式

```bash
cloudflared tunnel --url http://localhost:8765
# 复制输出的 https://xxxx.trycloudflare.com
# .env:
SHUXIN_WXPAY_NOTIFY_URL=https://xxxx.trycloudflare.com/api/payment/notify
```

改 `.env` 后执行：

```bash
bash scripts/redeploy_docker.sh
```

## 4. 小程序端

1. 微信商户平台绑定小程序 AppID
2. **DevTools 本地联调**：见上文 `build-local` + 不校验合法域名（默认 `http://localhost:8765`）
3. **真机 / 上线**：小程序后台配置 request 合法域名，并用 HTTPS 地址 build：

```bash
WECHAT_MINIPROGRAM_APPID=你的AppID \
  SHUXIN_API_BASE=https://你的API地址 \
  bash scripts/wechat_miniprogram_dev.sh build
```

## 5. 接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/payment/plans` | 套餐列表 |
| POST | `/api/payment/create-order` | 创建订单并返回 `uni.requestPayment` 参数 |
| POST | `/api/payment/orders` | 用户订单历史 |
| POST | `/api/payment/notify` | 微信支付回调（微信服务器调用） |

## 6. 注意事项

- `SHUXIN_WECHAT_MOCK=1` 时支付接口返回 503，避免 mock openid 误调真实微信支付
- 生产环境 `user_id` 即微信 `openid`，与 JSAPI 下单一致
- 回调验签失败时微信会重试；订单表 `out_trade_no` 唯一 + `status=paid` 幂等防重复充值
- 真机/上线必须使用**真实小程序 AppID** 编译，不能用 `touristappid`：

```bash
WECHAT_MINIPROGRAM_APPID=你的AppID SHUXIN_API_BASE=https://你的API bash scripts/wechat_miniprogram_dev.sh build
```

## 7. 生产上线迁移（本地联调通过后）

本地用 trycloudflare 跑通支付后，迁移到自有服务器时**不是只改一项**，但改动集中、商户证书可沿用。

### 7.1 本地 vs 生产对照

| 配置项 | 本地联调 | 生产 |
|--------|----------|------|
| `SHUXIN_WXPAY_NOTIFY_URL` | `https://xxx.trycloudflare.com/api/payment/notify` | `https://你的域名/api/payment/notify` |
| 小程序 API（编译时） | `http://localhost:8765`（`build-local`） | `https://你的域名`（`build`） |
| cloudflared | 仅 notify 需要 | **不需要** |
| 微信 request 合法域名 | 开发者工具可关校验 | **必须**添加生产域名 |
| 商户号 / 证书 / 公钥 / AppID | 已配好 | **通常不变**（同一商户号） |

```text
本地：  小程序 → trycloudflare → voice:8765
              微信回调 → trycloudflare → /api/payment/notify

生产：  小程序 → Nginx HTTPS → voice
              微信回调 → 你的域名 → /api/payment/notify
```

### 7.2 服务端迁移步骤

**1. 生产 `.env` 修改回调地址**

```bash
SHUXIN_WXPAY_NOTIFY_URL=https://你的域名/api/payment/notify
```

路径固定为 `/api/payment/notify`，只换域名。以下支付相关变量从开发机**原样复制**即可（同一商户号时无需重配）：

- `SHUXIN_WXPAY_MCHID`
- `SHUXIN_WXPAY_API_V3_KEY`
- `SHUXIN_WXPAY_CERT_SERIAL_NO`
- `SHUXIN_WXPAY_PRIVATE_KEY_PATH`（证书文件随 `data/certs/` 一起迁移）
- `SHUXIN_WXPAY_PUBLIC_KEY_PATH` / `SHUXIN_WXPAY_PUBLIC_KEY_ID`（公钥模式）
- `SHUXIN_WECHAT_APPID` / `SHUXIN_WECHAT_SECRET`

**2. 证书目录随 `data/` 一起迁**

确保生产机 `data/certs/` 含 `apiclient_key.pem`、`pub_key.pem` 等（见 §1）。

**3. 重部署**

```bash
bash scripts/redeploy_docker.sh
# 或生产：COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml bash scripts/redeploy_docker.sh
```

**4. 反代 / Nginx 要求**

- 有效 HTTPS 证书（微信不接受自签）
- 将 `POST /api/payment/notify` 转发到 voice 服务
- **保留**微信回调请求头（验签必需）：`Wechatpay-Signature`、`Wechatpay-Timestamp`、`Wechatpay-Nonce`、`Wechatpay-Serial`
- 不要改写 request body

**5. 公网可达性自检**

```bash
curl -sf https://你的域名/health
# notify 需 POST 才完整验证；至少确认 HTTPS 与路由存在
```

**6. 套餐价格（可选）**

联调用的 `data/payment_plans.json` 若为 0.01 元测试套餐，上线前改为正式价：

```bash
cp data/payment_plans.example.json data/payment_plans.json
# 编辑月卡/季卡/年卡金额后 redeploy
```

### 7.3 小程序迁移步骤

**1. 微信公众平台 → 开发管理 → 开发设置 → 服务器域名**

在 **request 合法域名** 添加：`你的域名`（不带 `https://` 和路径）

**2. 用生产 API 重编译并提交审核**

```bash
WECHAT_MINIPROGRAM_APPID=你的AppID \
SHUXIN_API_BASE=https://你的域名 \
bash scripts/wechat_miniprogram_dev.sh build
```

上传 `apps/wechat-miniprogram/dist/build/mp-weixin`。

### 7.4 上线验收清单

- [ ] 生产小程序登录 → 个人中心余额 `/api/users/quota` 正常
- [ ] 发起一笔小额真实支付（可先保留 0.01 元套餐做冒烟）
- [ ] Postgres `payment_orders`：`status=paid`，`paid_at` 有值
- [ ] 用户 DMX 余额 / `subscription_expires_at` 已增加
- [ ] voice 日志无 `notify verification failed`
- [ ] 已停用 cloudflared，`.env` 中无 trycloudflare 地址

### 7.5 常见故障

| 现象 | 可能原因 |
|------|----------|
| 能弹出支付但余额不涨 | `NOTIFY_URL` 仍指向 trycloudflare，或生产反代微信打不到回调 |
| 小程序 API 失败 | request 合法域名未配 / 仍用旧 trycloudflare 编译包 |
| 回调 404 | Nginx 未转发 `/api/payment/notify` |
| 回调验签失败 | 反代删了签名头或改写了 body |
| `APPID_MCHID_NOT_MATCH` | 商户平台未关联 AppID；或小程序 AppID 与 `.env` 不一致 |

支付凭证诊断（容器内）：

```bash
docker exec shuxin-voice-demo-pg python /app/scripts/diagnose_wxpay_certs.py
```

### 7.6 与整体部署的关系

Voice / Postgres / Qdrant 迁移见 [`DEPLOY_SERVER.md`](DEPLOY_SERVER.md)。支付迁移在 voice 服务与 `data/certs/` 就绪后，按本节 §7.2–7.4 执行即可。

