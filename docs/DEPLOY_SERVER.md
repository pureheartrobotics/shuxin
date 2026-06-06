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

## 语音服务

- [ ] `VOICE_DEMO_PORT` 与防火墙/反向代理一致
- [ ] `DATABASE_URL` 指向生产 Postgres

## 环境迁移（可选）

开发机迁到生产机时使用 `export_pack.sh` / `import_deploy.sh`（详见 [`VOICE_DEMO_MIN_TEST.md`](VOICE_DEMO_MIN_TEST.md) §12–13）：

- [ ] 源机 `bash scripts/export_pack.sh`，`BUNDLE_INFO.txt` 中 `包含 Postgres` / `包含 Qdrant` 为「是」
- [ ] 目标机先 `cd` 到安装目录，再 `bash scripts/import_deploy.sh <bundle>`（默认装当前目录）
- [ ] 目标机 `.env` 手动填写生产密钥与 `QDRANT_HTTP_PORT=6333`（bundle **不含** `.env`）
- [ ] import 完成后 `curl -sf http://127.0.0.1:8765/health`（端口按 `VOICE_DEMO_PORT` 调整）

## 本地端口冲突（仅开发机）

若仍报 `Bind for 0.0.0.0:6333 failed`：

```bash
docker ps --format '{{.Names}}\t{{.Ports}}' | grep 6333
# 在 .env 设 QDRANT_HTTP_PORT=6335，或停掉占用 6333 的旧容器
```
