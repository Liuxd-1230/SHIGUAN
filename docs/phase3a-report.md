# Phase 3A：本地优先传记提纲生成管线 —— 验收报告

> 日期：2026-08-03 ｜ 提交：本提交 ｜ 前置：Phase 2B M5.1（4c6084a）
>
> 目标：在不引入远程模型的前提下，打通「人物档案 → 确定性压缩 → LLM Provider（默认本地）→
> 提纲生成 → 校验/有限修复 → SQLite 持久化」的纵向管线；CI 全部使用 FakeLlmProvider。
> **绝不把模型想象伪装成事实**：模型只拿到确定性压缩档案，unresolved 数字人物名不进入自然语言摘要。

---

## 1. 分层职责

| 层 | 职责 | 说明 |
| --- | --- | --- |
| `biography-engine/py/providers/`（新） | LlmProvider 抽象 | Protocol（health / generate_json）+ `OpenAICompatibleProvider` + `FakeLlmProvider` + `build_provider` 工厂 + `ProviderError` 家族 |
| `biography-engine/py/config.py`（新） | Provider 配置 | 仅读环境变量（不覆盖 `.env`），`LLM_PROVIDER/BASE_URL/MODEL/API_KEY/TIMEOUT_SECONDS/TEMPERATURE/MAX_TOKENS/ALLOW_REMOTE` |
| `biography-engine/py/models.py`（新） | 压缩档案模型 | `CompressedProfile` / `CompressedEvent`，`COMPRESSION_VERSION="1"` |
| `biography-engine/py/importance.py`（新） | 事件重要度 | `score_event` 确定性评分分解（类型/confidence/证据/合并/日期/最高头衔/未解析降权） |
| `biography-engine/py/compressor.py`（新） | 确定性压缩 | `compress_profile`：强制保留出生/死亡/最高头衔 + 阶段代表 + 名额择优 |
| `biography-engine/py/prompt_builder.py`（新） | 版本化 Prompt | `PROMPT_VERSION="outline.zh-Hans.v1"`，只传压缩档案 + style + JSON Schema |
| `biography-engine/py/validators.py`（新） | 提纲校验 | eventIds 白名单 / 章节 id 唯一 / 时间大致有序 / 章节数 1–10 |
| `biography-engine/py/outline_generator.py`（新） | 生成编排 | 原始 1 次 + 修复 N 次（`DEFAULT_MAX_REPAIR=1`），非法输出不进保存 |
| `apps/server/app/routers/llm.py`（新） | 健康检查 | `GET /api/llm/health`（脱敏，绝不含密钥） |
| `apps/server/app/services/outline_store.py`（新） | SQLite 记录 | `data/biography-outlines.sqlite`，saveSignature 关联 + stale |
| `apps/server/app/routers/saves.py` | 提纲 API | `POST /local-saves/{id}/characters/{cid}/biography/outline` + `GET .../biography/outlines` |
| 前端 `OutlinePanel`（新） | 生成 UI | 模型状态 / 文风·上限·开关 / 点按钮才生成 / 章节展示 / 按 errorCode 提示 |
| 前端 `api.ts` | API 客户端 | `getLlmHealth` / `generateOutline` / `listOutlines` |

---

## 2. Provider 抽象与安全边界

- **默认本地**：`LLM_BASE_URL` 缺省 `http://127.0.0.1:8080/v1`；`is_local_url` 判定 localhost/127.0.0.1/::1。
- **远程显式放行**：非本地地址在 `LLM_ALLOW_REMOTE=false` 时，`health()` / `generate_json()` 直接抛
  `RemoteProviderDisabledError`（`remote_provider_disabled`），绝不静默外发。
- **密钥不泄漏**：API Key 只在构造 provider 时读入；`redact_base_url` 只暴露 `scheme://host:port`；
  日志/异常不含密钥与完整 Prompt；`test_outline_response_never_leaks_sensitive` 断言响应无 `sk-*`、无 staging 路径、无 user/system prompt。
- **CI 隔离**：`biography-engine` 58 项测试 + server outline API 10 项全部用 FakeLlmProvider；
  CI 不调用 OpenAI、不启动本地模型、不下载模型。
- **打开人物页面不自动生成**：前端只在点击「生成提纲」时调用 `generateOutline`；健康探测仅发最小 ping，不携带存档数据。

---

## 3. 确定性压缩（5.4/5.5）

- `score_event` 分解（全部可解释、可测试）：类型权重 + confidence（+10/-5/0）+ 证据（≥2 条 +5、1 条 +2、0 条 -10）
  + 合并（mergedCount>1 +3）+ 日期（有 +5、无 -10）+ 最高头衔（≥王国 +10、>0 +5）+ unresolved 相关实体（-8）。
- `_select_events`（受 `max_events` 硬上限约束）：① 出生/死亡（存在时）→ ② 最高等级头衔事件 → ③ 每十年阶段的代表事件（名额允许时补）→ ④ 分数降序择优。
- 同输入同配置 → 同输出（`test_same_input_same_output`）；`include_inferred/include_uncertain` 开关各自过滤。
- **本轮修复的真实 bug**：CK3 日期未零填充（`944.10.22` / `944.4.20`），字符串排序会把 10 月排到 4 月前，
  与真实时间顺序相反 → 提纲章节时间顺序校验误报倒置。修复为 `_date_key` 数值比较（与 `title_reign_extractor` 共用），
  新增回归测试 `test_selected_events_sorted_by_numeric_date`。
- **不伪造**：unresolved 数字人物名不写入 `relatedNames` / family/relationship facts，仅计入 `unresolvedCount` 并如实告警。

---

## 4. 提纲生成 + 校验 + 持久化（5.6–5.10）

- **Prompt 只含压缩档案**：`build_outline_prompts` 传入 `CompressedProfile` + `BiographyStyle` + `OUTLINE_JSON_SCHEMA`；
  `test_user_prompt_does_not_leak_raw_data` 断言无绝对路径 / `sk-*` / 令牌表字样。
- **有限修复重试**：Provider 输出解析失败（`ProviderOutputError`）与校验失败（errs）均可触发修复请求；
  超时/不可达/未配置为终态；`test_retry_exhaustion_when_fix_never_lands` 断言绝不无限重试。
- **校验器**：章节数 1–10、章节 id 唯一、`eventIds` 非空且全部来自压缩白名单、章节时间大致有序；
  非法输出不进保存（`valid=false` 记录 status=error）。
- **SQLite 记录**：`outline_generations(save_id, save_signature, character_id, style, status, outline_json,
  error_code, error_message, retry_count, warning_json, compression_version, prompt_version, created_at)`；
  同一存档重新解析（signature 变化）后旧记录 `stale=true`（`test_outlines_list_and_stale` 实测）。

---

## 5. 验证结果

- **契约** `packages/save-schema/py`：`pytest tests/` → **28 passed**（无契约改动，回归全绿）。
- **biography-engine**：`pytest` → **58 passed**（providers 13 / importance 10 / compressor 15 / validators 10 / prompt_builder 7 / outline_generator 11）。
- **后端**：无真实存档 `pytest tests/` → **198 passed / 13 skipped**（新增 `test_outline_api.py` 10 项：health 3 / 生成成功 / 未配置 / 不可达 / 400 / 404 / stale / 不泄漏密钥）。
- **前端**：`tsc --noEmit` 0 错；`npm run lint` 0 错 0 警告；`vitest` → **146 passed**（新增 `OutlinePanel` 7 项、`api` 3 项）；`vite build` 成功。
- **真实存档纵向验证**（`data/phase3a_real_verify.py`，本地运行、不提交；CI 不需要）：
  - melt + 索引：**2.3s**；玩家「仁赞」（id=22672）30 时间线事件 / 15 头衔 / 10 告警。
  - 压缩：selected=24（max_events=24）/ omitted=6 / unresolved=14（数字占位名如实计数，不伪造名字）。
  - 提纲（Echo Fake Provider）：**valid=True，8 章，24 事件引用，retry=0**；全程不访问真实模型服务。
- **Rust**：本轮未改动（回归由 CI rust 作业覆盖）。

---

## 6. 当前限制与下一轮建议

**限制**
- 未生成传记正文（Phase 3B）：正文生成、正文级事实校验、正文/提纲编辑保存仍未做。
- `POST /biography/outline` 同步阻塞生成（真实 LLM 长文本会慢）；如需超时容忍建议后续做异步任务。
- 本地模型需用户自行启动（llama.cpp / LM Studio / Ollama）；无模型时 UI 给出可操作提示而非伪造结果。
- 真实存档集成测试（`test_api.py` / `test_adapter.py` 中 44096 人、玩家 6432 等）是针对上一局游戏校准的；
  本机当前存档为 62148 人新局，7 项数据校准断言不匹配（与 Phase 3A 改动无关，测试文件未改动）。

**下一轮建议（Phase 3B）**
1. 正文生成：`POST /biography`（Chapters 每章追溯事件 id），复用 OutlineGenerator 重试模式 + `validate_style`。
2. 正文事实校验（步骤 8）：时间倒置 / 推断当事实 / 虚构配偶头衔 / 无证据对白等规则化校验 + 自动修正。
3. 生成历史 UI：前端展示 `GET /biography/outlines` 记录列表，支持加载旧提纲并提示 stale。
4. 异步生成：`LLM_GENERATE_ASYNC=true` 时先返回 recordId，前端轮询。
5. 端到端冒烟：用户启动本地 llama.cpp 后，跑一次真实「选人 → 生成提纲 → 展示章节」全链路。
