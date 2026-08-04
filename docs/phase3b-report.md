# Phase 3B 报告：正文逐章生成 + 确定性事实校验

> 交接文档 Phase 3B 全部完成。分支 master，两次提交中的第二次
> `feat(3B): chapter generation and deterministic fact checking`。

## 一、本轮解决的问题

Phase 3A 只到「提纲」。3B 把管线推进到「正文」：

1. **逐章生成**：正文不再一次性让模型自由发挥，而是以已生成提纲为依据，
   每章一次模型调用，且**只传该章允许的事件**（`compressed.selectedEvents`
   过滤到 `chapter.eventIds`），杜绝章节间事件串用。
2. **确定性事实校验**：正文必须通过 20 条确定性规则（不调用 LLM），
   发现问题只重传该章、最多 2 次；重试耗尽仍不达标 → 保存为
   `needs_revision` 草稿，**绝不伪装成功**。
3. **持久化与异步**：正文/修订历史落 SQLite（`data/biography-biographies.sqlite`），
   生成走后台任务（POST → jobId → 轮询进度 → 可取消）。

## 二、关键设计

### 1. 章节 Prompt（`chapter_prompts.py`）

- `CHAPTER_PROMPT_VERSION = "biography-chapter.zh-Hans.v1"`，版本号即文件名。
- `build_chapter_prompts(compressed, chapter_outline, style)` 返回
  `(system_prompt, user_prompt)`：
  - 共享块：身份/家庭/头衔/关系/亲属/统治·战争·告警摘要（3A.1 产物，技术字段已过滤）；
  - 独立块：`## 本章允许事件`——只有本章 eventIds 对应的事件列表；
  - 生成要求：只写有据事实、不虚构对白/心理描写、推断用「据推断」、
    防御战争写「卷入/抵御」、不泄漏数字 id/tXXXX/路径/内部枚举/markdown。

### 2. BiographyGenerator（`biography_generator.py`）

- `generate(profile, outline, ..., on_progress, is_cancelled)`：
  1. 确定性压缩（与提纲同源）；校验提纲事件全部仍在压缩选择内（否则
     `outline_event_missing`）。
  2. 逐章：`_generate_chapter` → 结构校验（章节 id 与提纲一致、eventIds ⊆ 本章白名单）
     → FactChecker 单章子集校验 → 有问题且未耗尽重试 → 只重传该章（`build_chapter_repair_prompt`）。
  3. 汇总：全部 PASS → `completed`；任一重试耗尽 → `needs_revision`；Provider 级错误 → error。
- 进度/取消：`on_progress(completed, total)` 每章回调；`is_cancelled()` 每章前检查。
- `DEFAULT_MAX_CHAPTER_REPAIR = 2`（原始 1 + 修复至多 2 次，绝不无限重试）。

### 3. FactChecker（`fact_checker.py`，20 规则）

| # | 规则 | 级别 | 说明 |
|---|------|------|------|
| 1 | event_id_not_allowed | ERROR | 章节引用了不在该章允许列表的事件 |
| 2 | event_after_death | WARNING | 引用事件日期晚于人物死亡日期 |
| 3 | time_reversal | WARNING | 正文日期与本章事件明显冲突（过早/过晚） |
| 4 | numeric_id_leak | ERROR | 裸数字人物/头衔 id（≥5 位连续数字） |
| 5 | token_id_leak | ERROR | tXXXX 占位 token |
| 6 | source_path_leak | ERROR | 存档路径片段 / 内部 key |
| 7 | internal_enum_leak | WARNING | snake_case 内部枚举（title_gain 等） |
| 8 | punctuation_double | WARNING | 「。。」「；。」等连续标点 |
| 9 | inferred_as_fact | WARNING | 只依据推断事件却无推断措辞 |
| 10 | conflict_as_succession | WARNING | 头衔变更写成「继承」且无 succession 事件 |
| 11 | defender_as_declared | ERROR | 防御战争写成「宣战/主动进攻」 |
| 12 | fabricated_dialogue | ERROR | 虚构对白/心理描写 |
| 13 | unverified_quoted_name | WARNING | 引号内人名不在已知档案事实中 |
| 14 | unverified_quoted_title | WARNING | 引号内头衔名不在已知头衔中 |
| 15 | death_year_mismatch | WARNING | 正文自述死亡年份与存档不符 |
| 16 | birth_year_mismatch | WARNING | 正文自述出生年份与存档不符 |
| 17 | profile_id_leak | ERROR | 正文含人物原始数字 id（与 4 同检测） |
| 18 | model_meta_leak | WARNING | JSON/schema/prompt 等模型元信息 |
| 19 | empty_chapter | ERROR | 章节正文为空 |
| 20 | markdown_leak | WARNING | markdown 围栏/链接/标题标记 |

输出 `FactCheckResult(status: pass|needs_revision, issues: FactCheckIssue[])`。

### 4. 持久化（`biography_store.py`）

- 表 `biographies`：`id`(uuid 主键)/save_id/save_signature/character_id/outline_id/
  style/status/revision_count/biography_json/fact_check_json/model_name/
  prompt_version/compression_version/created_at/updated_at。
- 存档重解析（signature 变化）→ 旧记录 `stale=true`。
- **绝不存**：API Key、完整 Prompt、本地路径、原始存档。

### 5. 异步任务 API（`biography_jobs.py` + `saves.py` 路由）

- `POST /api/local-saves/{id}/characters/{cid}/biography`
  body `{outlineId, includeInferred, includeUncertain, maxEvents}` → `{jobId, status:"pending"}`。
  outlineId 必须存在且 signature 与当前存档一致（否则 404/400）。
- `GET /api/biography/jobs/{job_id}` → status/totalChapters/completedChapters/
  currentChapter/currentChapterTitle/retryCount/factCheckIssueCount/biographyId/
  recordStatus/error。
- `POST /api/biography/jobs/{job_id}/cancel`。
- `GET /api/local-saves/{id}/characters/{cid}/biographies` → 记录列表（含 stale）。
- 模型不可达/未配置 → job=error、不保存半成品、不伪造成功。

### 6. 前端（`BiographyPanel.tsx` + `api.ts`）

- 三层层级清晰：史料摘要（确定性）→ AI 提纲（OutlinePanel）→ AI 正文（BiographyPanel）。
- 打开页面不自动调用模型；先选非 stale 提纲再「生成正文」。
- 进度条（role=progressbar）+ 当前章节 + 完成计数 + 取消按钮。
- 记录卡片：completed/needs_revision 徽标 + stale 标记 + 事实校验提示列表。
- 模型不可达 → 结构化错误提示，不影响档案浏览。

## 三、验证结果

| 套件 | 结果 |
|------|------|
| 契约 `save-schema` | **29 passed**（无契约改动，回归全绿） |
| biography-engine | **117 passed**（FactChecker 26 / chapter_prompts 4 / biography_generator 9） |
| 后端 pytest | **240 passed / 13 skipped**（`test_biography_api.py` 10 项） |
| Rust | **24 passed**（无改动，回归全绿） |
| 前端 | vitest **165 passed**（BiographyPanel 5 项）；tsc / eslint 0 错；vite build 成功 |

真实存档冒烟（`data/phase3b_smoke.py`，本地不提交）：
- 注册真实存档 → 档案「摩那卢」(id=67147747) → Echo 提纲（1 章）→
  真实 OpenAICompatibleProvider（默认 http://127.0.0.1:8080/v1，模型未运行）
  → `provider_unreachable`、biography=None —— **诚实失败，未伪造成功**。

## 四、当前限制

1. **端到端真机正文尚未生成**：本地 8080 无模型运行。用户启动
   llama.cpp/LM Studio/Ollama（OpenAI 兼容、默认 8080）后重跑
   `python data/phase3b_smoke.py` 即可完成完整端到端冒烟。
2. 每次正文生成基于单份提纲；文风/事件上限固定取生成提纲时的设置（3B 前端
   暂不提供独立正文设置，改动会影响提纲一致性）。
3. `needs_revision` 记录不提供「人工修订后重新校验」的编辑 UI（留待 Phase 4）。

## 五、下一轮建议

1. **端到端真机冒烟**：启动本地模型后验证真实正文生成 + FactChecker 通过率。
2. 正文编辑/保存 UI（修订 `needs_revision` 草稿后可重新校验）。
3. 家族树/地点/导出（Phase 4）。
