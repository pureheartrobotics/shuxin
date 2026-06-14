# 生产服务器部署检查清单

本地开发默认 `QDRANT_HTTP_PORT=6335`，避免与本机其它 Qdrant（常见占用 **6333**，如 GrepAI）冲突。  
**上线前请逐项核对，勿把本地 `.env` 原样复制到服务器。**

## Qdrant / Mem0

- [ ] `.env` 中 **`QDRANT_HTTP_PORT=6333`**（不要用本地的 `6335`），或按运维规范**不映射** Qdrant 到公网（仅 compose 内网 `qdrant:6333`）
- [ ] `SHUXIN_MEM0_ENABLED=1`
- [ ] `DEMO_LLM_API_KEY`（及 `DEMO_LLM_BASE_URL`）已配置（Mem0 抽取与 embedding）
- [ ] `SHUXIN_QDRANT_COLLECTION=shuxin_memories`（勿与其它项目共用 collection）
- [ ] 服务器上验收：`curl -sf http://127.0.0.1:6333/readyz`（按实际映射端口调整）

## Docker

- [ ] `docker compose build` 含 `requirements-voice-app.txt` 层（mem0 / qdrant-client）
- [ ] `docker compose up -d` 后 `shuxin-qdrant`、`shuxin-postgres`、`shuxin-voice-demo-pg` 均为 healthy / running
- [ ] 生产启动使用 `COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml`（无 `./src` 热挂载）

## 语音服务

- [ ] `VOICE_DEMO_PORT` 与防火墙/反向代理一致
- [ ] `DATABASE_URL` 指向生产 Postgres

## 微信支付（小程序充值）

本地联调细节见 [`PAYMENT_DEV_SETUP.md`](PAYMENT_DEV_SETUP.md)。上线核对：

- [ ] `data/certs/` 已迁移：`apiclient_key.pem`、`pub_key.pem`（公钥模式）
- [ ] `.env` 中 `SHUXIN_WXPAY_NOTIFY_URL=https://你的域名/api/payment/notify`（**勿**留 trycloudflare）
- [ ] 其余 `SHUXIN_WXPAY_*`、`SHUXIN_WECHAT_APPID` / `SECRET` 与联调环境一致（同一商户号）
- [ ] Nginx 转发 `/api/payment/notify` 并保留 `Wechatpay-*` 签名头
- [ ] 微信公众平台 request 合法域名已添加生产 API 域名
- [ ] 小程序已用 `SHUXIN_API_BASE=https://你的域名` 重编译并发布
- [ ] `data/payment_plans.json` 已从 0.01 元测试价改为正式套餐（若需要）
- [ ] 冒烟：真实支付 → `payment_orders.status=paid` → 用户余额增加

## 环境迁移（可选）

开发机迁到生产机时使用 `export_pack.sh` / `import_deploy.sh`（详见 [`VOICE_DEMO_MIN_TEST.md`](VOICE_DEMO_MIN_TEST.md) §12–13）：

- [ ] 源机 `bash scripts/export_pack.sh`，`BUNDLE_INFO.txt` 中 `包含 Postgres` / `包含 Qdrant` 为「是」
- [ ] 目标机先 `cd` 到安装目录，再 `bash scripts/import_deploy.sh <bundle>`（默认装当前目录）
- [ ] 目标机 `.env` 手动填写生产密钥与 `QDRANT_HTTP_PORT=6333`（bundle **不含** `.env`）
- [ ] import 完成后 `curl -sf http://127.0.0.1:8765/health`（端口按 `VOICE_DEMO_PORT` 调整）

## 阶段 A：同机大磁盘（bind mount）

系统盘偏小、已挂载数据盘时，把用户文件与音频输出挪到大分区，**Postgres/Qdrant 仍在本机 Docker volume**。

1. 停栈：`docker compose -p shuxin down`（或 `bash scripts/redeploy_docker.sh` 前先 down）
2. 建目录并迁移（示例挂载点 `/mnt/shuxin`，按实际磁盘修改）：

```bash
sudo mkdir -p /mnt/shuxin/{data,outputs,models,samples}
sudo rsync -a ./data/ /mnt/shuxin/data/
sudo rsync -a ./outputs/ /mnt/shuxin/outputs/
sudo rsync -a ./models/ /mnt/shuxin/models/
[[ -d samples ]] && sudo rsync -a ./samples/ /mnt/shuxin/samples/
sudo chown -R "$(id -u)":"$(id -g)" /mnt/shuxin
```

3. 在 `.env` 写入（**宿主机绝对路径**）：

```bash
SHUXIN_HOST_DATA_DIR=/mnt/shuxin/data
SHUXIN_HOST_OUTPUTS_DIR=/mnt/shuxin/outputs
SHUXIN_HOST_MODELS_DIR=/mnt/shuxin/models
SHUXIN_HOST_SAMPLES_DIR=/mnt/shuxin/samples
```

4. 生产建议叠加 `docker-compose.prod.yml`（无 `./src` 热挂载）：

```bash
export COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml
bash scripts/redeploy_docker.sh
```

5. 验收：

```bash
docker inspect shuxin-voice-demo-pg --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}' | grep /app/data
du -sh "${SHUXIN_HOST_DATA_DIR:-./data}" "${SHUXIN_HOST_OUTPUTS_DIR:-./outputs}" "${SHUXIN_HOST_MODELS_DIR:-./models}"
curl -sf http://127.0.0.1:${VOICE_DEMO_PORT:-8765}/health
```

**注意**：`SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY` 与 `data/` 必须一起迁；换路径后旧项目目录下的 `./data` 可归档删除。

阶段 C（另购存储机、Postgres 外置端口）见迁移规划文档，本期不做。

## 本地端口冲突（仅开发机）

若仍报 `Bind for 0.0.0.0:6333 failed`：

```bash
docker ps --format '{{.Names}}\t{{.Ports}}' | grep 6333
# 在 .env 设 QDRANT_HTTP_PORT=6335，或停掉占用 6333 的旧容器
```
