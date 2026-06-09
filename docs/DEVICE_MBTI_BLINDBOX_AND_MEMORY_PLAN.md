# 舒心硬件机器人：盲盒 MBTI 与设备级记忆 — 产品需求与实施规划

> **⚠️ 内部文档**：含架构、存储、接口等实现细节，**请勿对外或交给 GPT 评审**。  
> 对外请使用：[MBTI_BLINDBOX_PRODUCT_CONCEPT.md](MBTI_BLINDBOX_PRODUCT_CONCEPT.md)

> **文档用途**：团队内部评审与开发排期。  
> **状态**：v0.2 — Phase 2–4（盲盒内容 / 状态机 / 开箱 UX）已在 Voice + 小程序落地；Phase 1 设备级记忆、Admin 重置盲盒仍为后续。  
> **关联项目**：舒心（ShuXin）语音硬件 + 陪伴型 Agent 框架。  
> **相关文档**：[VOICE_ARCHITECTURE.md](VOICE_ARCHITECTURE.md)、[COMPANION_ROBOT_PERSONALITY_DESIGN.md](COMPANION_ROBOT_PERSONALITY_DESIGN.md)（长期人格成长，本期不实施）

---

## 一、背景

### 1.1 产品是什么

「舒心」是一个**陪伴型 AI 智能体**，面向实体硬件机器人场景：

- 用户通过微信小程序绑定设备；
- 设备通过 WebSocket 与云端语音服务通信（STT → LLM Agent → TTS）；
- Agent 具备固定灵魂（`SOUL.md`）、MBTI 行为因子、自尊/情感/守护等陪伴插件，以及短期 + 中期 + 长期记忆。

当前语音栈已具备：Postgres 用户/设备/绑定、火山复刻 TTS、按 `users.agent_id` 选音色、出厂批量制码、硬件 Opus 音频、Mem0 + Qdrant 长期记忆等能力。

### 1.2 为什么要做这一期

我们希望在**硬件交付体验**上形成差异化：

1. **盲盒人格**：每台机器人出厂时带一个随机的 MBTI 气质（16 型之一），用户首次连接时「开箱」得知——同一用户的多台机器可能性格不同，增加收集感与话题性。
2. **一台机器人一份记忆**：用户可能拥有多台设备；每台设备应像「独立的陪伴体」，对话历史、长期记忆、陪伴状态不应在设备之间混用。
3. **MBTI 需要可运营的内容**：不仅是代码里的 16 型标签，还需要为每型撰写专属的 SOUL 语气片段，让盲盒开出后在对话中可感知。

### 1.3 与「长期人格成长」的关系

仓库内 [COMPANION_ROBOT_PERSONALITY_DESIGN.md](COMPANION_ROBOT_PERSONALITY_DESIGN.md) 描述的是**跨会话缓慢漂移**的成长维度（温暖度、主动性等）。

**本期规划聚焦**：

- 出厂/首次连接时的 **MBTI 盲盒**（静态种子，开箱后锁定）；
- **记忆与绑定关系**改造。

长期成长系统可在本期落地后再迭代，不在本期范围。

---

## 二、需求陈述

### 2.1 用户故事

| 编号 | 角色 | 故事 | 优先级 |
|------|------|------|--------|
| US-1 | 购买者 | 我绑定第一台机器人时，希望有一个「开箱」仪式，告诉我这台机器人的 MBTI 类型和一句话气质描述 | P0 |
| US-2 | 多机用户 | 我拥有两台机器人时，希望它们记住的内容互相独立，和不同的「伙伴」聊天 | P0 |
| US-3 | 单机用户 | 我解绑后再绑回同一台设备，希望恢复之前和**这台设备**的对话记忆，而不是丢失 | P1 |
| US-4 | 二手转让 | 我把设备送给朋友后，朋友绑定时不应看到我的对话内容 | P0 |
| US-5 | 运营/售后 | 我需要在后台看到设备的 MBTI 与开箱状态，必要时重置盲盒 | P1 |
| US-6 | 内容团队 | 我需要为 16 种 MBTI 各写一段可注入 Agent 的语气文案 | P0 |

### 2.2 功能需求（FR）

#### FR-1 盲盒 MBTI

- **FR-1.1** 每台设备在生命周期内有一个 MBTI 类型，取自标准 16 型（INFJ、ENFP 等）。
- **FR-1.2** 类型在出厂制码时可预分配（便于测试），但对用户处于「未开箱」状态，直到首次连接。
- **FR-1.3** 首次连接时触发开箱：小程序展示结果；设备端 TTS/协议事件同步告知。
- **FR-1.4** 开箱完成后状态锁定，同一设备不会再次随机。
- **FR-1.5** Admin 可重置盲盒（售后），重置后重新 random 并回到未开箱状态；可选清空该设备相关记忆（需二次确认）。

#### FR-2 MBTI 内容

- **FR-2.1** 每种 MBTI 有独立配置文件，至少包含：类型名、展示用 tagline、注入 Agent 的 soul_snippet（200–400 字量级）。
- **FR-2.2** 可选：在系统已有行为因子基线上做小幅 delta 微调。
- **FR-2.3** 音色仍由用户级 `agent_id` 决定（火山复刻）；MBTI 只影响语气与人格表达，不改变 TTS 音色。

#### FR-3 设备级记忆

- **FR-3.1** 记忆命名空间键为 **`(user_id, device_id)`**，而非当前的 `user_id`  alone。
- **FR-3.2** 以下数据均按 `(user, device)` 隔离：
  - 短期对话原文；
  - 中期 rolling summary；
  - 长期 Mem0 / Qdrant 向量；
  - 陪伴插件状态（自尊、情感等）。
- **FR-3.3** 解绑：不删除 `(user, device)` 存储，视为冷存档。
- **FR-3.4** 新用户绑定已解绑过的设备：使用新键 `(new_user, device_id)`，从空记忆开始。
- **FR-3.5** 原用户再次绑定同一设备：恢复 `(原_user, device_id)` 的历史。

#### FR-4 一人多机

- **FR-4.1** 一个用户可 active 绑定多台设备（现有 `device_bindings` 已支持）。
- **FR-4.2** 每台设备可有不同 MBTI；同一用户下多台设备记忆互不串扰。

### 2.3 非功能需求（NFR）

- **NFR-1** 开箱与记忆改造不应破坏现有 WebSocket 硬件协议的主流程（hello / listen / TTS）。
- **NFR-2** 须有 E2E 测试覆盖：双设备隔离、解绑换用户、再绑恢复。
- **NFR-3** 须有数据迁移方案，避免生产环境升级后用户记忆全部丢失（策略可讨论：迁移 vs 接受新键从零开始）。
- **NFR-4** MBTI 配置文件须可校验（16 型齐全、字段合法），便于 CI。

### 2.4 明确不做（Out of Scope）

- 用户自助重抽盲盒；
- 跨设备合并记忆或「一个账号一份人格」；
- 非 16 型的自定义盲盒池（本期固定 MBTI）；
- 开箱后 MBTI 随时间自动变化（属长期成长文档范畴）；
- 更换 MBTI 但保留记忆的细粒度策略（Admin 重置默认清空该设备记忆）。

---

## 三、已对齐的产品决策

以下决策已在团队讨论中确认（Grill-me 对齐）：

| 编号 | 议题 | 决策 |
|------|------|------|
| D-1 | 记忆归属模型 | **(user_id, device_id)** 复合键 |
| D-2 | 记忆分层范围 | 短期 + 中期 + 长期 + 陪伴状态 **全部** 按 (user, device) 隔离 |
| D-3 | MBTI 内容形态 | **16 型** + 每型 **SOUL/语气文案** + 可选行为因子微调 |
| D-4 | 开箱时机 | **首次连接**开箱 → 锁定；Admin 可重置 |
| D-5 | 开箱渠道 | **小程序绑定页** + **设备首次 hello**（双端一致） |
| D-6 | 音色 vs 气质 | **分离**：`users.agent_id` → 音色；`devices.metadata.mbti` → 语气盲盒 |
| D-7 | 解绑后数据 | **保留** `(user, device)` 冷存档；新用户不继承 |
| D-8 | 小程序解绑 | **不提供**用户自助解绑；换绑仅 Admin/售后 |

---

## 四、现状与差距（简要）

### 4.1 已有

- 出厂制码（batch / 单台 `provision_device`）写入 `metadata.mbti` + `mbti_status=sealed`；
- `data/mbti/mbti_profiles.yaml`（16 型）+ `load_mbti_profiles()`；Slot2 `style_anchor`、Slot4 `micro_anchor`；
- 盲盒状态机：`sealed` → `locked`；`mbti_revealed_by`（`miniprogram_bind` | `first_hello`）；`device_intro_played` 控制 TTS 自我介绍仅一次；
- 小程序绑定：`POST /api/devices/bind` 返回 `mbti` 卡片 + `MbtiRevealModal` 弹窗；设备列表展示 MBTI 徽章；**用户侧无解绑**；
- WebSocket：`hello` 后 `mbti/reveal`（仅 hello 抢先揭晓时）+ `reveal_script` TTS；小程序已揭晓时 hello **补播**自我介绍；`_ensure_runtime` 以 `agent is None` 初始化运行时（device 可先由 intro 预填）；
- Admin：设备 Tab MBTI 下拉、`PATCH /admin/api/devices/{id}/mbti`（不改 `mbti_status`）；
- `VoiceService.apply_device_mbti()`、多设备 binding、Mem0 + rolling summary、陪伴插件已接入语音路径。

### 4.2 差距

| 能力 | 现状 | 目标 |
|------|------|------|
| 记忆路径 | `users/{user_id}/...` 多设备共享 | `users/{user_id}/devices/{device_id}/...` |
| Mem0 user_id | 从目录解析仅 user | 复合键 |
| Postgres 中期摘要 | `shared_memory(user_id)` | `(user_id, device_id)` |
| Admin 重置盲盒 | 未实现 | 售后 reset + 审计 + 可选清记忆 |
| bind 后设备在线即时 TTS | WS 注册表 + bind API 推送；离线则 hello 补播 | 已实现 |

---

## 五、方案概述

### 5.1 盲盒生命周期（状态机，已实现版）

```
制码 → mbti 已分配, mbti_status=sealed（用户未知）
  ↓ 小程序扫码绑定（主路径）或设备 hello（边缘：用户先开机）
locked + mbti_revealed_by + device_intro_played=false
  ↓ 小程序弹窗展示类型；设备 hello 补播 reveal_script TTS 一次
device_intro_played=true（不再重复开箱/自我介绍）
  ↓ Admin reset（售后，未实现）
sealed + 新 mbti（可选清空记忆）
```

**devices.metadata 字段（代码）**：

```json
{
  "mbti": "INFJ",
  "mbti_status": "sealed | locked",
  "mbti_revealed_at": "ISO8601",
  "mbti_revealed_by": "first_hello | miniprogram_bind",
  "device_intro_played": false
}
```

旧设备仅有 `mbti`、无 `mbti_status`：视为已锁定，不重复小程序开箱；hello 可按 `device_intro_played` 补播一次。

### 5.2 记忆目录（目标）

```text
data/shuxin_home/users/{user_id}/devices/{device_id}/
  memory/       # Mem0 / facts.json
  companion/    # 陪伴插件
  summaries/    # rolling_summary
```

Mem0 / Qdrant 的 logical `user_id` 建议：`{user_id}__{device_id}` 或等价编码。

### 5.3 MBTI 内容文件（目标）

```text
data/mbti/
  README.md           # 写作规范
  INFJ.yaml …         # 共 16 份
```

**单文件 schema 示例**：

```yaml
type: INFJ
display_name: 提倡者
tagline: "安静而神秘，记得你说过的小事"
soul_snippet: |
  你是 INFJ 气质的舒心：……
companion_factor_delta:   # 可选
  empathy: 0.02
```

### 5.4 开箱交互（已实现）

- **小程序绑定** `POST /api/devices/bind` 成功响应（`sealed` 时揭晓）：
  ```json
  {
    "binding_id": "...",
    "device_code": "SX-000001",
    "already_bound": false,
    "mbti": {
      "is_first_reveal": true,
      "mbti": "INFJ",
      "display_name": "提倡者",
      "tagline": "安静而神秘，记得你说过的小事"
    }
  }
  ```
  UI：`MbtiRevealModal` 弹窗；`already_bound` 或 hello 已揭晓时 `is_first_reveal: false`。
- **WebSocket**（hello 抢先揭晓时，或补播自我介绍前的 `agent/reply`）：
  ```json
  {"type": "mbti/reveal", "mbti": "INFJ", "tagline": "...", "is_first_reveal": true}
  ```
- **隐私**：`mbti_status=sealed` 时 `POST /api/devices/my` 的 `device.metadata` **不含** `mbti`。
- **Admin**：设备列表 mbti + status 徽章；改型 `PATCH .../mbti`；「重置盲盒」待做。

---

## 六、分阶段实施计划

| Phase | 名称 | 主要交付 | 依赖 |
|-------|------|----------|------|
| **1** | 设备级记忆 | 目录/Mem0/DB 复合键、解绑语义、E2E 测试 | — |
| **2** | MBTI 内容 | 16 YAML（产品写）+ loader + 校验脚本 | 可与 1 并行 |
| **3** | 盲盒状态机 | metadata 状态、bind/WS reveal、Admin reset | 1, 2 |
| **4** | 开箱 UX | 小程序弹窗、设备 TTS、Admin MBTI 下拉 | 3 |
| **5** | 迁移与验收 | 旧数据迁移脚本、文档更新、AC 验收 | 1–4 |

**建议顺序**：1 →（2 并行）→ 3 → 4 → 5。

---

## 七、验收标准（Acceptance Criteria）

| 编号 | 验收项 |
|------|--------|
| AC-1 | 同一用户绑定设备 A、B，A 上对话不会被 B 的上下文/Mem0/陪伴状态召回 |
| AC-2 | 设备 A 从用户 1 解绑、用户 2 绑定后，用户 2 看不到用户 1 在该设备上的记忆 |
| AC-3 | 用户 1 再次绑定设备 A，可恢复 `(user1, deviceA)` 历史 |
| AC-4 | 首次连接触发开箱；之后 status=locked，不再随机 |
| AC-5 | 同音色（同 agent_id）下，不同 MBTI 设备语气可区分 |
| AC-6 | Admin 可查看并重置盲盒，有审计记录 |

---

## 八、风险与开放问题（供 GPT / 评审重点看）

1. **Mem0 迁移**：复合 `user_id` 变更后，旧向量是否批量 re-index，还是新环境接受从零？生产需运维决策。
2. **浏览器 demo**：无真实 hardware `device_id` 时，是否用固定 synthetic id（如 `web-demo`）？
3. **Admin 重置粒度**：重置 MBTI 是否必须清空该 device 下所有 `(user, device)` 记忆？V1 建议「必须清空 + 二次确认」。
4. **文案进度**：16 型全部写完前，是否允许 fallback 到 `identity.py` 通用描述？
5. **与长期成长的关系**：MBTI 是静态种子；后续是否在 MBTI 基线上叠加 [COMPANION_ROBOT_PERSONALITY_DESIGN.md](COMPANION_ROBOT_PERSONALITY_DESIGN.md) 的漂移维度？建议 V2 再议。
6. **隐私与二手设备**：解绑后冷存档保留在用户+设备键下；若设备多次流转，是否需「恢复出厂设置」一键 wipe device 全部键？可列为 V2。

---

## 九、分工建议

| 角色 | 职责 |
|------|------|
| 产品 / 文案 | 16 型 YAML 撰写、开箱文案、验收 AC-4/AC-5 |
| 后端 | Phase 1/3/5 记忆与状态机、API、迁移 |
| 小程序 | Phase 4 绑定页开箱 UI |
| 硬件 / 固件 | Phase 4 处理 `mbti/reveal`、TTS 播报 |
| 运维 | Mem0 迁移策略、生产 rollout |

---

## 十、给外部评估者的说明（GPT 评审提示）

若你将本文档交给 GPT 评估，可附带以下问题：

1. **(user_id, device_id)** 记忆模型在陪伴硬件场景下是否合理？有无更好的键设计？
2. **盲盒 MBTI 开箱后锁定**是否符合用户预期？二手转让场景有无漏洞？
3. **音色（user 级）与气质（device 级）分离**是否清晰？会否让用户困惑？
4. **Phase 顺序**是否依赖正确？有无更小的 MVP 切片？
5. **Mem0 复合键迁移**业界常见做法是什么？
6. 与「长期人格成长」两套系统并存时，如何避免人格漂移过大？

---

## 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v0.1 | 2026-06-07 | 初稿：背景、需求、决策、Phase、AC、风险 |
| v0.2 | 2026-06-08 | 对齐实现：sealed→locked、小程序弹窗、hello 补播 TTS、my 脱敏；用户侧无解绑 |
