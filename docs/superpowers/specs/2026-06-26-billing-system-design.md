# 初心 (ChuXin) — 用户多维度消费账单与异步计费系统设计文档

本文档定义了初心陪伴型 AI 智能体框架中，面向小程序端用户的多维度消费（LLM、STT、TTS）账单统计、异步后台计费以及 Admin 后台管理系统的完整设计规范。

---

## 1. 核心设计原则

1. **极致简约与苹果美学 (Apple-style Aesthetics)**
   Admin 后台采用卡片化布局，提供直观的比例条、数据汇总和流畅的微交互（如删除行时左滑淡出、价格修改自动保存等），避免冗余操作。
2. **非阻塞异步计费 (Non-blocking Async Logging)**
   计费逻辑完全脱离语音会话（STT -> LLM -> TTS）的主流程核心时间线。使用后台任务（Background Task）执行数据库写入，确保对实时 WebSocket 交互的 TTFT（首包延迟）和整体延迟产生零影响。
3. **高内聚、松耦合模块化 (Modular & Decoupled)**
   引入独立的 `BillingService` 模块，封装所有的费用计算、单价获取和缓存策略。主业务逻辑只需调用统一的方法入口，预留极高的后续扩展性。
4. **安全与容错性 (Robustness & Fault Isolation)**
   计费服务内部捕获并处理所有数据库及网络异常，计费系统故障绝对不会影响用户的正常语音对话体验。

---

## 2. 数据库设计

通过新建迁移文件 `src/shuxin/voice/migrations/011_user_expenditures.sql` 引入计费相关的表结构与初始数据。

### 2.1 消费流水明细表 (`user_expenditures`)

| 字段名 | 类型 | 约束 | 描述 |
| :--- | :--- | :--- | :--- |
| `expenditure_id` | TEXT | PRIMARY KEY | 计费记录唯一标识 (UUID) |
| `user_id` | TEXT | NOT NULL, REFERENCES users(user_id) | 关联的小程序用户 ID |
| `type` | TEXT | NOT NULL, CHECK (type IN ('stt', 'tts', 'llm')) | 消费服务类型 |
| `model` | TEXT | NOT NULL DEFAULT '' | 使用的具体模型或渠道名称 |
| `usage_amount` | DOUBLE PRECISION | NOT NULL DEFAULT 0 | 原始使用量（STT：秒，TTS：字数，LLM：token数） |
| `cost_yuan` | NUMERIC(12, 6) | NOT NULL DEFAULT 0.000000 | 折算后的人民币金额（元） |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 扣费生成时间 |

#### 索引设计
```sql
CREATE INDEX IF NOT EXISTS idx_expenditures_user_date 
    ON user_expenditures (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_expenditures_date 
    ON user_expenditures (created_at DESC);
```

### 2.2 全局价格配置 (`platform_settings`)

利用现有的 `platform_settings` 表存储价格单价。其 `value` 字段存储 JSON 结构：

*   **Key**: `pricing.stt`
    *   **Value**: `{"tencent-realtime": 0.0002}` (每秒单价，折合每分钟 0.012 元)
*   **Key**: `pricing.tts`
    *   **Value**: `{"volcengine-clone": 0.00002}` (每字符单价，折合每万字 0.2 元)
*   **Key**: `pricing.llm`
    *   **Value**: `{"deepseek-chat": 0.000002}` (每 token 单价，折合每百万 token 2 元，支持按模型细分)

---

## 3. 模块架构与数据流

### 3.1 架构拓扑

```
+-------------------------------------------------------------+
|                     WebSocket Client                        |
+------------------------------+------------------------------+
                               | Voice Streaming
                               v
+------------------------------+------------------------------+
|                    src/shuxin/voice/server.py               |
|  - Runs STT, LLM, TTS loop                                  |
|  - Completes dialogue turn and sends audio to client        |
+------------------------------+------------------------------+
                               | asyncio.create_task() (Fire-and-forget)
                               v
+------------------------------+------------------------------+
|                   src/shuxin/voice/billing.py               |
|  - BillingService (Calculates cost, queries cached prices)  |
+------------------------------+------------------------------+
                               | db.pool.execute()
                               v
+------------------------------+------------------------------+
|                     PostgreSQL Database                     |
|  - Table: user_expenditures                                 |
|  - Table: platform_settings                                 |
+-------------------------------------------------------------+
```

### 3.2 计费核心服务 `BillingService`
服务封装在 `src/shuxin/voice/billing.py` 中。具备以下职责：
1. **价格缓存策略**：将 `platform_settings` 中的单价字典缓存在内存中（有效期 5 分钟），规避同步查库的开销。
2. **安全记录入口**：提供 `record_usage_in_background` 方法，内部包裹 `try-except` 以确保异常完全隔离。

---

## 4. Admin 后台界面与交互设计

Admin 后台采用单页应用中的独立 Tab（“消费账单”）呈现，引入 Apple 风格的卡片式视觉与交互逻辑：

### 4.1 视觉布局

1. **月度开销看板（顶部卡片组）**
   *   **「本月总支出」**：大字号字重展示，例如 `¥ 142.80`。下方是一个多彩分段指示条，红色代表 LLM、蓝色代表 STT、绿色代表 TTS，宽度比例与金额占比完全一致。
   *   **「服务均价与效率」**：展示本月对话总轮数及每轮对话的均价。
   *   **「快捷账单清空」**：包含月份选择下拉框 and 醒目的「清空当月账单」按钮。
2. **控制与工作区（中部与底部）**
   *   使用圆角 Segmented Control 切换 **「消费明细流水」** 和 **「服务价格配置」**。
   *   **明细流水列表**：每条数据配有类型圆形微图标，右侧显示绿色的 `+¥0.0120` 金额。鼠标悬停时，右侧划出红色的「删除」微图标。
   *   **价格配置表单**：列表化的输入项，每个输入框失去焦点或停止输入 1 秒后自动通过 `PATCH` API 提交保存，并显示绿色的已保存勾选微标。

### 4.2 核心微交互
*   **删除流水**：点击删除单条流水后，该行列表条目向左平滑滑出并高度折叠消失。顶部卡片的「本月总支出」金额会通过动画滚减至新数值。
*   **清空确认**：点击「清空当月账单」时，背景微弱磨砂模糊，弹出一个圆角卡片提示确认，防止管理员误操作。

---

## 5. API 接口规范

所有的 API 请求与响应均遵循 RESTful 规范，基准路径为 `/admin/api`：

### 5.1 获取账单汇总统计
*   **请求**: `GET /admin/api/billing/summary?month=2026-06`
*   **响应**:
    ```json
    {
      "success": true,
      "data": {
        "total_cost": 142.80,
        "breakdown": {
          "llm": {"cost": 85.68, "percentage": 60.0},
          "stt": {"cost": 28.56, "percentage": 20.0},
          "tts": {"cost": 28.56, "percentage": 20.0}
        },
        "total_turns": 3173,
        "average_turn_cost": 0.045
      }
    }
    ```

### 5.2 分页获取消费明细流水
*   **请求**: `GET /admin/api/billing/records?month=2026-06&user_id=xxx&limit=20&cursor=xxx`
*   **响应**:
    ```json
    {
      "success": true,
      "data": {
        "items": [
          {
            "id": "exp_83f8d...",
            "user_id": "wx_user_001",
            "type": "stt",
            "model": "tencent-realtime",
            "usage_amount": 12.5,
            "cost_yuan": 0.0025,
            "created_at": "2026-06-26T11:20:00+08:00"
          }
        ],
        "next_cursor": "ey..."
      }
    }
    ```

### 5.3 删除单条流水记录
*   **请求**: `DELETE /admin/api/billing/records/{id}`
*   **响应**: `{"success": true}`

### 5.4 批量清空指定月份数据
*   **请求**: `DELETE /admin/api/billing/records/months/{year_month}` (例如 `2026-06`)
*   **响应**: `{"success": true, "deleted_count": 1258}`

### 5.5 获取与更新价格配置
*   **获取定价**: `GET /admin/api/billing/pricing`
*   **响应**:
    ```json
    {
      "success": true,
      "data": {
        "stt": {
          "tencent-realtime": 0.0002
        },
        "tts": {
          "volcengine-clone": 0.00002
        },
        "llm": {
          "deepseek-chat": 0.000002,
          "default": 0.000002
        }
      }
    }
    ```
*   **更新定价**: `PATCH /admin/api/billing/pricing`
*   **请求体**:
    ```json
    {
      "stt": {
        "tencent-realtime": 0.00025
      }
    }
    ```
*   **响应**: `{"success": true}`
