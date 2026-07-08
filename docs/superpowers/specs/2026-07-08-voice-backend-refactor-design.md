# 语音后端架构重构设计文档

**日期**：2026-07-08  
**作者**：架构评审  
**状态**：✅ 已确认，待实施  

---

## 1. 问题陈述

`src/shuxin/voice/server.py`（4620 行）和 `postgres_repository.py`（4834 行）是整个项目最重的两个文件，分别承担了 7 类和 11 类完全无关的职责。

**量化指标（现状）：**

- `server.py`：81 个 `except Exception`、93 个 `JSONResponse({"error": ...})`、17 个 `except PermissionError`——每个路由独立重复错误处理模板
- `postgres_repository.py`：单一类 `VoicePostgresRepository` 包含设备管理、支付/订阅、工厂验收、计费、记忆摘要、公告、MBTI 盲盒、附件、绑定等 11 个业务领域的 SQL
- 无任何 FastAPI Middleware；无统一异常处理；无 Depends 依赖注入（`miniapp_admin.py` 除外）

---

## 2. 设计目标

1. **局部性（Locality）**：修改一个业务域只需读一个 ~200 行文件，不再翻 4620 行
2. **接缝（Seam）清晰**：每个 Router 模块有明确的领域边界，可独立 mock 测试
3. **横切关注点统一（AOP）**：鉴权、错误处理、依赖注入通过 FastAPI 原生机制一次声明，不在业务代码中重复
4. **测试面改善**：测试导入路径与职责对齐
5. **不改变业务逻辑**：所有重构是结构性移动，不修改任何路由处理逻辑

---

## 3. 目标文件结构

```
src/shuxin/voice/
├── server.py              # App 工厂 + startup/shutdown（~250 行）
├── ws_session.py          # _VoiceWebSocketSession（从 server.py 移出，~1120 行）
│
├── routers/               # 新增目录
│   ├── __init__.py
│   ├── deps.py            # 共享依赖：get_repo / get_billing / require_admin
│   ├── exception_handlers.py  # 全局异常处理器（AOP 切面）
│   ├── user.py            # 用户/设备/公告/反馈域（~180 行）
│   ├── payment.py         # 支付/订单/充值域（~150 行）
│   ├── factory.py         # 工厂验收 QA 域（~180 行）
│   └── admin.py           # Admin 后台域（~350 行，40+ 个路由）
│
├── static/                # 新增目录
│   ├── admin.html         # 从 _admin_html() 提取（1659 行字符串 → 真实文件）
│   └── demo.html          # 从 _web_demo_html() 提取（410 行字符串 → 真实文件）
│
└── (以下文件保持不变)
    ├── miniapp_admin.py   # 已正确拆分，不动
    ├── billing.py
    ├── service.py
    ├── postgres_repository.py  # 本次不拆（Phase 4 阶段）
    └── ...（其他模块）
```

---

## 4. AOP 层设计

### 4.1 Spring Boot → FastAPI 映射

| Spring Boot 概念 | FastAPI 等价机制 | 本次实现 |
|---|---|---|
| `@ControllerAdvice` 全局异常 | `app.exception_handler()` | `exception_handlers.py` |
| `@PreAuthorize` 方法级鉴权 | `Depends(require_admin)` | `deps.py` + Router 级声明 |
| `@Around` 环绕拦截 | `BaseHTTPMiddleware` | `RequestLogMiddleware`（可选） |
| `@Autowired` 依赖注入 | `Depends(get_repo)` | `deps.py` |
| Plugin AOP Hook（已有） | `invoke_hook()` | 保持现状，Voice 层扩展预留 |

### 4.2 routers/deps.py — 共享依赖

```python
from fastapi import Request

def get_repo(request: Request):
    value = getattr(request.app.state, "repo", None)
    if value is None:
        raise RuntimeError("voice repository is not initialized")
    return value

def get_billing(request: Request):
    value = getattr(request.app.state, "billing", None)
    if value is None:
        raise RuntimeError("billing service is not initialized")
    return value

def require_admin(request: Request) -> None:
    admin_token = getattr(request.app.state, "admin_token", "")
    provided = (
        request.headers.get("X-Admin-Token")
        or request.cookies.get("shuxin_admin")
    )
    if not admin_token:
        raise PermissionError("SHUXIN_ADMIN_TOKEN is required for admin access")
    if provided != admin_token:
        raise PermissionError("invalid admin token")
```

### 4.3 routers/exception_handlers.py — 全局异常处理器

消除 server.py 中 81 个 `except Exception` 和 17 个 `except PermissionError`。

```python
from fastapi import Request
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger("shuxin.voice.api")

async def permission_error_handler(request: Request, exc: PermissionError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=403)

async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=400)

async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"error": str(exc)}, status_code=500)

def register_exception_handlers(app) -> None:
    app.add_exception_handler(PermissionError, permission_error_handler)
    app.add_exception_handler(ValueError, value_error_handler)
    app.add_exception_handler(Exception, generic_error_handler)
```

路由函数内部改为直接 `raise`，不再 `return JSONResponse({"error": ...})`。

### 4.4 Router 级鉴权声明

Admin Router 通过构造时声明 `dependencies`，40+ 个路由自动全覆盖：

```python
# routers/admin.py
router = APIRouter(
    prefix="/admin/api",
    dependencies=[Depends(require_admin)],
    tags=["Admin"],
)

@router.get("/devices")
async def list_devices(repo=Depends(get_repo), limit: int = 50, cursor: str = "", q: str = ""):
    return await repo.list_devices(limit=limit, cursor=cursor, q=q)
    # 无 try/except、无 require_admin()
```

---

## 5. 路由域划分

### 5.1 routers/user.py（~180 行）

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/barcodes/decode` | POST | 条码解码 |
| `/api/wechat/login` | POST | 微信登录 |
| `/api/users/quota` | POST | 用户配额查询 |
| `/api/users/me` | POST | 用户信息 |
| `/api/announcements` | GET | 活动公告 |
| `/api/feedbacks` | POST | 用户反馈 |
| `/api/devices/bind` | POST | 设备绑定 |
| `/api/devices/unbind` | POST | 解绑 |
| `/api/devices/my` | POST | 我的设备列表 |

### 5.2 routers/payment.py（~150 行）

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/payment/plans` | GET | 充值套餐列表 |
| `/api/payment/orders` | POST | 创建支付订单 |
| `/api/payment/orders` | GET | 订单列表 |
| `/api/payment/notify` | POST | 微信支付回调 |

### 5.3 routers/factory.py（~180 行）

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/factory/verify` | POST | 工厂验收扫码 |
| `/api/factory/verify-logs` | GET | 工厂验收日志 |
| `/admin/api/factory/verify-summary` | GET | Admin 验收汇总 |
| `/api/devices/provision` | POST | 设备预置 |
| `/admin/api/factory/provision-batch` | POST | 批量制码 |
| `/admin/api/factory/next-sequence` | GET | 下一设备序号 |

> factory.py 内混合 `/api/` 和 `/admin/api/` 路由，Admin 路由单独加 `Depends(require_admin)` 而非 Router 级声明。

### 5.4 routers/admin.py（~350 行）

包含 40+ 个纯 Admin 路由，通过 Router 级 `dependencies=[Depends(require_admin)]` 统一保护：
- 设备管理（CRUD、MBTI、密钥轮换、label）
- 用户管理（patch、quota、top-up）
- Agent 管理（CRUD、soul_path）
- 计费（pricing、billing records、monthly summary）
- 绑定管理、Adapter 调用、TTS 预览
- STT/TTS 默认值批量应用、LLM 平台默认配置

---

## 6. ws_session.py 独立

将 `_VoiceWebSocketSession`（server.py L1418–L2533）**整体移动**到 `ws_session.py`，内部逻辑完全不变。

同时移出的辅助函数：`_pop_speakable_segments`、`_negotiate_audio_params`、`_client_ip_from_websocket`、`_elapsed_ms`

**测试影响（import 路径改动，逻辑零改动）：**

| 测试文件 | 变更 |
|---|---|
| test_voice_quota_gate.py | `server` → `ws_session` |
| test_voice_web_demo_wire.py | `server` → `ws_session` |
| test_voice_streaming_segments.py | `server` → `ws_session` |
| test_ensure_runtime_after_mbti_prefetch.py | `server` → `ws_session` |
| test_voice_auth_gate.py | `server` → `ws_session` |
| test_first_listen_latency_optimization.py | `server` → `ws_session` |
| test_voice_opus_downlink.py | `server` → `ws_session` |
| test_opus_codec.py | `server` → `ws_session` |
| test_admin_tabs.py | `_admin_html` 函数 → `static/admin.html` 文件内容断言 |

---

## 7. static/ HTML 外置

将 `_admin_html()`（1659 行）和 `_web_demo_html()`（410 行）提取为真实 HTML 文件。

`default_device_id` 参数通过 JS 运行时获取（URL 参数或 `/api/voice/status` 接口）。

```python
# server.py 路由改写
STATIC_DIR = Path(__file__).parent / "static"

@app.get("/admin")
async def admin_page():
    return FileResponse(STATIC_DIR / "admin.html")

@app.get("/")
async def demo_page():
    return FileResponse(STATIC_DIR / "demo.html")
```

---

## 8. 执行阶段与验收标准

### Phase 0 — AOP 基础设施

建立 `routers/deps.py` + `routers/exception_handlers.py`，注册到 app（现有路由暂不改）。

**验收**：`pytest tests/` 全通；新增 `tests/test_deps.py`

### Phase 1 — HTML 外置（0 逻辑改动）

提取 `static/admin.html` + `static/demo.html`，删除两个 HTML 函数。

**验收**：`pytest tests/test_admin_tabs.py`；浏览器 `/admin` 正常

### Phase 2 — 路由 Router 化

建四个 Router 模块；server.py 改为 include_router；路由内部去 try/except。

**验收**：`pytest tests/` 全通；`wc -l server.py` < 300

### Phase 3 — ws_session.py 独立

移动 `_VoiceWebSocketSession`；修复 9 个测试文件 import 路径。

**验收**：`pytest tests/` 全通；`grep "_VoiceWebSocketSession" server.py` 无结果

### Phase 4（后续可选）— postgres_repository 领域拆分

从 `FactoryRepository`（最独立）开始，逐域拆分。跨域事务（`fulfill_payment_order`）保留 shared connection 策略。

---

## 9. 约束与不变量

- `postgres_repository.py` Phase 0–3 不拆，接口保持稳定
- `_VoiceWebSocketSession` 内部逻辑、self 结构、实例变量**不变**
- AGENTS.md 中所有并发约束（`_ensure_runtime` 设备覆写、WebSocket 作用域约束）继续有效
- Python 3.8 兼容性：类型声明使用 `Optional[...]` 而非 `... | None`
- 计费（`billing.record_usage_in_background`）继续在 `_process_turn` 中直接调用，Voice Plugin Hook 扩展留待后续

---

## 10. 文件行数预测

| 文件 | 当前 | 目标 |
|---|---|---|
| server.py | 4,620 | ~250 |
| ws_session.py | 新建 | ~1,120 |
| routers/user.py | 新建 | ~180 |
| routers/payment.py | 新建 | ~150 |
| routers/factory.py | 新建 | ~180 |
| routers/admin.py | 新建 | ~350 |
| routers/deps.py | 新建 | ~50 |
| routers/exception_handlers.py | 新建 | ~40 |
| static/admin.html | 新建 | ~1,659 |
| static/demo.html | 新建 | ~410 |
