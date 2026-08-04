# AGENTS.md —— 面向后续 AI 轮次的工作约定

本文件供在 SHIGUAN 项目中工作的自主开发 Agent（包括后续轮次的自己）阅读。
它浓缩了产品规范中最容易踩坑的边界，确保每轮都在同一套约束下安全推进。

---

## 0. 项目身份

- 项目名：**史官 SHIGUAN**；标语：**读取存档，重写一生。**
- 定位：基于真实 CK3 存档证据，为人物立传的 AI 史官。**绝不把模型想象伪装成事实。**
- 当作长期迭代的完整产品，而非一次性 Demo。

## 1. 硬性安全边界（每次都必须遵守）

- 只读写 `D:/funproject/SHIGUAN` 范围内的文件。
- 不执行 `rm -rf` / `del /s` / `git reset --hard` 等破坏性命令。
- 不删除用户已有文件；不执行 `git push`；不创建 PR。
- 默认不提交 Git，除非本轮明确要求。
- 不覆盖 `.env`；不写入真实 API Key；不下载/运行来源不明的可执行文件。
- 引入第三方项目前检查许可证；不把现有开源项目大量源码直接复制进项目。
- 修改 Python 后运行 `py_compile` 与相关 pytest；修改 TS/JS 后运行 `tsc --noEmit` + eslint + `vite build`。
- 测试失败必须修复或回滚，不留明显无法启动的状态。

## 2. 每轮工作方式（强制顺序）

1. 先读 README / AGENTS / docs / 相关源码，了解现状（读 `docs/roadmap.md` 看当前 Phase）。
2. 说明本轮要解决的具体问题。
3. 先调查现状，再修改代码。
4. 优先完成一条可实际验证的纵向功能，避免大规模无关重构。
5. 为重要逻辑补充测试。
6. 执行构建 / 类型检查 / 测试。
7. 最后汇报：修改了什么、为什么、如何验证、当前限制、下一轮建议。

## 3. 解析策略（最关键，详见 docs/save-format-notes.md）

- 明文侧（text / text_zip / 解压后 gamestate）：自研 Python PDX 文本解析器。
- 二进制 / 铁人侧（binary_zip / binary / ironman）：Rakaly CLI 适配器 `melt` 为明文后再走文本解析。
- **铁律**：二进制需要外部组件时——检查是否存在；不存在给清楚安装提示；不得静默失败；不得把二进制当文本强行解析；不得伪造解析成功。
- 铁人解码需用户自备令牌表（`RAKALY_IRONMAN_TOKENS_PATH`），不得随项目分发，也不得公开推导方法。
- 不采用依赖第三方 exe 的方案（如 scorpdx/ck3json 导出器）。
- 所有解析库通过 `SaveParserAdapter` 协议隔离，UI/LLM 不直接依赖其内部结构。

## 4. 数据契约（唯一事实来源）

- TS：`packages/save-schema/src/types.ts`
- Python：`packages/save-schema/py/models.py`
- 修改字段时二者必须同步，并同步更新 `docs/architecture.md` 的模型说明。
- 严格镜像规则（Phase 0.5 收口）：所有 TS 联合类型在 Python 侧用 `Enum`（`str, Enum`）表达，
  **不得退化为任意字符串**，且必须有运行时校验。已约束：`SaveKind`、`Encoding`、
  `RelationshipType`（`RelationshipPeriod.type`）、`WarRole`（`WarParticipation.role`）、
  `FactCheckStatus`（`FactCheckResult.status`）、`SaveInspection.encoding`。
- 核心类型：`CharacterProfile`（原始数据层）、`TimelineEvent`（带 `confidence` 与 `evidence: EvidenceRef[]`，
  以及 `mergedCount?: number` —— >1 表示由 N 条重复存档记录去重合并，前端据此显示「已合并 N 条记录」徽标）、
  `EvidenceWarning`、`Biography`（展示层，只引用事件 ID）。
- 人物索引/档案分离：`ParsedSave.characterIndex`（`CharacterSummary[]` 轻量摘要）与
  `ParsedSave.profiles`（`Record<id, CharacterProfile>` 按需完整档案）分开，避免大型存档一次性生成全部完整 Profile。
- Mock 隔离：测试/Mock 数据必须用 `FixtureEnvelope<T>` 包裹（`isMock` / `source` / `schemaVersion` / `generatedFor` / `data`），
  Mock 元数据不与真实业务模型（如 `CharacterProfile`）混合。
- `confidence`：`confirmed` / `inferred` / `uncertain`。推断不得写成确定事实。
- 契约测试：`packages/save-schema/py/tests/test_contract.py`（pytest）；TS 侧 `tsconfig.json` 严格模式 `tsc --strict --noEmit`。
  修改契约后必须跑这两项验证。

## 5. 传记管线（详见 docs/biography-pipeline.md）

八步：解析 → 索引 → 标准档案 → 时间线 → 压缩 → 提纲 → 正文 → 事实校验。
- 两次模型调用：先提纲（每章 `eventIds` 非空且来自时间线），再正文（每章追溯事件 ID）。
- 事实校验自动进行，发现问题要求模型修正，不展示错误内容。
- 禁止虚构对白 / 内心活动 / 战役细节 / 篡改时间关系。

## 6. 目录约定

- 不为符合目录而制造空包。`apps/*`、`packages/shared`、`packages/biography-engine`、`scripts` 在对应 Phase 才建立。
- 真实存档 / 数据库 / 上传目录（`data/`、`*.ck3` 等）已被 `.gitignore` 忽略，不提交。
- `.env` 被忽略；`.env.example` 不含真实密钥。

## 7. 当前状态（Phase 0.5 + 1A + 1B + 1C + 1C.1 + 2A + 2A.1 + 2B M1–M5 + M5.1，均已完成）

已建立：数据契约（TS+Python 严格同步 + 契约测试）、四份 docs、`.env.example`、`.gitignore`、README、AGENTS、fixtures/mock 契约、TS 严格类型检查环境、前端工程骨架 `apps/web`（Vite+React+TS strict+Tailwind+Zustand+Framer Motion+PWA 安全缓存）；可运行的 Mock 纵向链路（选择页→传记页→时间线↔证据面板双向同步）；索引/档案按需加载；`validateProfileEnvelope` 运行时校验；基于 History API 的可靠路由；`MockParseService` 确定性解析状态机；东方数字史馆设计语言（通道化 Design Token + 共享组件库 + 四页面改造）；键盘可达性（skip-link / 焦点管理 / 44px 触控）、移动端单栏重排、Framer Motion `MotionConfig reducedMotion="user"` + CSS 媒体查询双重 reduced-motion；加载竞态修复（按人物的 `profileRequestStateById` + `requestId`）；`/design-lab` 视觉实验室；PWA 缓存策略纯函数 `swCachePolicy.ts`；ESLint 8 链路（`npm run lint` / `lint:fix`）；Vitest 前端测试 132 项（含 `CharacterCard.test.tsx` 5 项、`TitlesPanel.test.tsx` 3 项、`MemoriesPanel.test.tsx` 5 项、`BiographyPage.test.tsx` 12 项、`swHandler.test.ts` 13 项、`RealParsePage.test.tsx` 3 项）。
**后端（Phase 2A + 2A.1 + 2B）**：`tools/ck3-reader` Rust sidecar（ck3save 0.4.3 MIT，真实/占位 token 表由 `build.sh` 依 `CK3_IRONMAN_TOKENS` 决定，占位表随仓库、真实表用户自备不随分发）；FastAPI 后端（adapters/services/routers）；本地存档发现 + 目录监听 + Mod 兼容报告 + 安全导入 + 真实分页路由；人物索引/按需档案（一次 melt、多次查询，`data/cache/<saveId>/<signature>/`，`reader_version` + **二进制指纹门禁**防占位/真实 token 表构建交叉复用缓存）；M1 反推真实 token + 三容器 44096 人物；M2 实体索引 + `ReferenceResolver`（未命中 `name=原id` 不编造）；M3 头衔与统治经历（Rust `scan_titles` 19003 条 → Python `TitleProfileIndex`，5230 名现任统治者；`CharacterProfile.titles` + `title_gain/title_loss/succession` 事件全带 EvidenceRef；`CharacterSummary.primaryTitle/highestTitleTier/isRuler`；`GET /local-saves/{id}/characters/{cid}/titles`；真实 token 表下中文头衔如 `教宗国`/`幽蓟`）；M4 关系与记忆深化（Rust `scan_memories` → `memories.json`（28675 条 / 116 类型，participants 角色表 / dates / battle_location）+ `scan_characters_full` 增 6 婚姻历史字段；Python `MemoryTimelineIndex` 按「主体角色表 + family_data 交叉核对」归属（married 6543→6498 = 99.3%，owner 为全局计数器不可解码）、became_* 同日期成对推断好友/宿敌/恋人（标 `inferred` + 告警，未配对只计数不伪造名）、imprisoned 等 owner 非 participant 类型诚实跳过并计数；`CharacterProfile.memories` + 记忆时间线事件（全带 EvidenceRef）+ `friends/rivals/lovers/siblings` + `spouses`（`isFormer`/`betrothed`/`concubine`）；`GET /local-saves/{id}/characters/{cid}/memories`；前端 `MemoriesPanel`）。M5 时间线去重合并 + 搜索/导入/人名中文化：契约 `TimelineEvent.mergedCount` 双端同步；`timeline_builder.py` `merge_timeline` 纯函数（去重键 `(type, date, 首位 related id)`、**无日期不合并**、证据按 id 聚合、`mergedCount=组大小`、`TimelineMergeResult` 含 `merge_details`），`to_profile` 基础/头衔/记忆三来源统一合并（实测抽样 2000 人 239 人 = 11.9% 有 child_birth 重复，合并后同键 0）；`GET /local-saves/{id}/characters/{cid}/timeline`；搜索修复（`q` 匹配解析后字段 + 头衔名，LRU 缓存 name key→解析名；`title=` 按 holder id 集合过滤）；**loader 缺失重建**（重启/直达 URL 名字仍中文，修复"搜不到"关键 bug）；人名中文化（`resolve_display_name`：loc key → 本地化表 / 拼音hex 如 `Zhongrong_4EF2_5BB9` Unicode 确定性解码「仲容」/ 拉丁名 `Maurizio` 走游戏 `character_names_l_simp_chinese.yml`「毛里齐奥」；全未命中回退原 id 不伪造；`names/` 子目录被 `**/*.yml` 覆盖）；前端 `RealParsePage`（`/saves/:saveId/parse`，真实后端 3 阶段 inspect→mods→parse，失败重试成功落印）+ `TimelineNode` 合并徽标 + `api.getTimeline`。M5.1 LLM 前数据完整性收口：① 无实体锚点事件**不再误合并**（`_dedup_key` 无锚点返回 None，仅同 type+date+同可靠锚点才合并）；② `CharacterRef.resolved` 双端契约 + 统一引用构建 `_character_ref_for`（父母/子女/兄弟姐妹/好友/宿敌/恋人 by_id+loader 解析、unresolved→原 id+resolved=False、列表按 id 去重）+ `memory_timeline_extractor._char_ref` 同步；③ LLM 输入过滤 `sanitize_character_ref_for_llm`（`resolved=false` 且数字名不写入摘要，保留 id 不编造占位）；④ 前端 `contractValidate` 补 CharacterRef 结构校验。测试基线：后端 pytest 201 项（含真实存档集成，无样本时 188 passed / 13 skipped）、契约 28、Rust 20 项（CI 已含 `cargo test --release`）、前端 136 项 + tsc + eslint + vite build。
**Phase 1C.1 收口**：东方素材 WebP 化（PNG 约 6.49 MB → WebP 约 1.11 MB，CSS `image-set` 回退）+ 移出 4 张参考图至 `docs/design-reference/`（不进 `dist`/`git`）；`ParsePage` 移除 eslint-disable 改 `useCallback` 并修 `exhaustive-deps`（`npm run lint` 零错误零警告）；`docs/ASSET_AUDIT.md` 素材审计表；经用户授权推送到公开远端。
未建立：真实 token 表下发的中文化收尾（M3.2 之后）、传记管线 LLM（Phase 3）、家族树/地点/导出（Phase 4）。
下一轮见 `docs/roadmap.md` 的 Phase 2B M5.2（真实关系字段对比）与 Phase 3（LLM 传记管线）。

## 8. 沟通风格

面向用户的汇报用简体中文，结论先行、给出可验证证据（命令输出/文件路径/测试结果），
并明确列出"当前限制"与"下一轮建议"。不要只给建议——能安全完成的工作直接在项目内完成。
