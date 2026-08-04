# 史官 SHIGUAN —— 架构文档

> 产品标语：**读取存档，重写一生。**
> 定位：基于真实存档证据，为《十字军之王 III》人物立传的 AI 史官。

本文档描述系统总体架构、分层管线、解析策略与工程约定。它是后续各 Phase 的实现依据，会随开发演进持续更新。

---

## 1. 设计原则（不可妥协）

1. **证据优先**：任何进入传记的内容都必须追溯到存档数据。模型想象不得伪装成既成事实。
2. **两层分离**：`原始数据层`（存档里真实存在的东西）与 `传记展示层`（模型生成的文字）严格分离。标准人物档案只描述"有什么"，传记只描述"怎么写"，且正文必须引用时间线事件 ID。
3. **不伪造**：二进制/铁人存档若缺少外部解析器，必须显式报错并给出安装提示，绝不静默失败，绝不把二进制当文本强行解析，绝不伪造"解析成功"。
4. **隐私默认本地**：存档默认只在本地处理；远程模型需用户显式开启，且只发送压缩后的结构化档案，不发送完整存档。
5. **适配器隔离**：所有外部解析库都通过 `SaveParserAdapter` 协议隔离，UI 与 LLM 逻辑不得直接依赖某个解析库的内部结构。
6. **克制的技术栈**：前端 React + TS + Vite + Tailwind + Zustand + Framer Motion（仅必要过渡）；后端 Python 3.11+ + FastAPI + Pydantic + SQLite。不为炫技引入多余依赖。

---

## 2. 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                        Web (React + TS)                      │
│  起始页 · 解析页 · 人物选择页 · 人物传记页 · 家族页 · 设置页  │
│  Zustand 状态 · Tailwind 样式 · PWA(manifest + 离线壳)       │
└───────────────▲──────────────────────────┬──────────────────┘
                │  REST / WebSocket         │
┌───────────────┴──────────────────────────▼──────────────────┐
│                   Server (FastAPI + Python)                  │
│                                                              │
│  ┌────────────┐   ┌────────────┐   ┌────────────────────┐   │
│  │ 上传/检测   │ → │ 解析管线    │ → │  索引 + 标准档案    │   │
│  └────────────┘   └─────┬──────┘   └─────────┬──────────┘   │
│                         │                     │              │
│            ┌────────────▼───────────┐        │              │
│            │  SaveParserAdapter      │        │              │
│            │  - PlaintextAdapter     │        │              │
│            │  - RakalyCliAdapter      │        │              │
│            └────────────┬───────────┘        │              │
│                         │                     │              │
│  ┌──────────────────────▼──────────┐  ┌─────▼─────────────┐ │
│  │  Biography Engine (Phase 3)      │  │  SQLite 存储       │ │
│  │  压缩 → 提纲 → 正文 → 事实校验   │  │  项目/索引/记录    │ │
│  └──────────────────────────────────┘  └───────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 目录布局（当前已建立 / 后续填充）

```
SHIGUAN/
├─ apps/
│  ├─ web/            # ✅ Phase 1A–1C 已完成：React + Vite + TS(strict) + Tailwind + Zustand + Framer Motion + 东方视觉/响应式/无障碍 + ESLint
│  │  ├─ src/
│  │  │  ├─ App.tsx           # 视图路由（start/parse/select/bio）+ 过渡
│  │  │  ├─ store.ts          # Zustand：ParsedSave / 选中人物 / 搜索筛选
│  │  │  ├─ lib/loadMock.ts   # 载入 FixtureEnvelope<MockDataset> → ParsedSave
│  │  │  ├─ lib/buildOutline.ts # 从时间线确定性生成章节提纲
│  │  │  ├─ pages/            # StartPage / ParsePage / SelectPage / BiographyPage
│  │  │  └─ components/       # Header / CharacterCard / Timeline / EvidencePanel / MuseumSurface / ScrollPanel / SealButton / InkDivider / PortraitFrame / EvidenceBadge / TimelineNode / PageHeading / EmptyState / AssetImage / icons / DesignLabPage
│  │  ├─ public/             # manifest.webmanifest + icon.svg + sw.js（PWA 骨架）
│  │  ├─ vite.config.ts      # @shiguan/save-schema / @mock 别名
│  │  └─ tsconfig.json       # strict 模式
│  └─ server/         # FastAPI 后端（Phase 2 建立）
├─ packages/
│  ├─ shared/         # 前后端共享工具（Phase 1+）
│  ├─ biography-engine/  # 传记生成与校验（Phase 3）
│  └─ save-schema/    # ✅ Phase 0.5 已完成：数据契约（TS+Python 同步 + 契约测试）
│     ├─ src/types.ts # TS 类型（事实来源）
│     ├─ py/models.py # Pydantic 镜像（Enum 严格约束）
│     ├─ py/tests/    # 契约运行时校验（pytest）
│     └─ tsconfig.json# TS 严格类型检查配置
├─ fixtures/
│  ├─ mock/           # ✅ 已建：Phase 1 用的可信 Mock 数据（明确标注非真实解析）
│  └─ README.md
├─ docs/              # ✅ 已建：本文档 + save-format-notes / biography-pipeline / roadmap
├─ scripts/           # 后续：构建、检查、解析辅助脚本（Phase 1+）
├─ .env.example       # ✅ 已建：不含真实密钥
├─ .gitignore         # ✅ 已建
├─ README.md          # ✅ 已建
└─ AGENTS.md          # ✅ 已建：面向后续 AI 轮次的工作约定
```

> 原则：不为符合目录而制造空包。`apps/*`、`packages/shared`、`packages/biography-engine`、`scripts` 将在对应 Phase 才建立。

---

## 3. 分层数据管线（核心流程）

完整流程严格遵循产品规范第四节，绝不允许把整个存档直接塞给模型。

| 步骤 | 产物 | 负责模块 | 状态 |
|---|---|---|---|
| 1. 解析原始存档 | 可访问的数据结构 | SaveParserAdapter | Phase 2 |
| 2. 建立索引 | characters/dynasties/houses/titles/counties/cultures/faiths/relationships/wars/memories/localization | 索引器 | Phase 2 |
| 3. 标准人物档案 | `CharacterProfile` | 档案构建器 | Phase 2 |
| 4. 构建时间线 | `TimelineEvent[]`（带 confidence） | 时间线构建器 | Phase 2 |
| 5. 事件排序与压缩 | 去重/合并/过滤/重要度打分后的精简事件集 | 压缩器 | Phase 3 |
| 6. 生成传记提纲 | `BiographyOutline`（每节引用事件 ID） | 传记引擎（首次调用） | Phase 3 |
| 7. 生成正文 | `Biography`（每节追溯事件 ID） | 传记引擎（二次调用） | Phase 3 |
| 8. 事实校验 | `FactCheckResult` | 校验器 | Phase 3 |

数据契约见 `packages/save-schema/src/types.ts`。每一层只向下游交付明确类型，UI/LLM 不直接触达解析库内部结构。

### 3.1 数据契约关键模型（Phase 0.5 收口）

为保证"绝不把模型想象伪装成事实"，契约层在 Phase 0.5 做了以下收口：

- **TS/Python 严格镜像**：所有 TS 联合类型在 Python 侧用 `Enum`（`str, Enum`）表达，运行时不接受任意字符串。已严格约束：`SaveKind`、`Encoding`、`RelationshipPeriod.type`（`RelationshipType`）、`WarParticipation.role`（`WarRole`）、`FactCheckResult.status`（`FactCheckStatus`）、`SaveInspection.encoding`。
- **人物摘要与完整档案分离**：`ParsedSave` 同时持有 `characterIndex: CharacterIndexEntry[]`（轻量摘要，供选择页）与 `profiles: Record<id, CharacterProfile>`（按需完整档案）。避免大型存档一次性生成全部完整 Profile。
- **`CharacterSummary` / `CharacterIndexEntry`**：选择页用的摘要模型（id/name/sex/生卒/王朝/文化/信仰/主要头衔/最高头衔等级/是否统治者/是否在世/是否玩家王朝/肖像 key/证据告警计数）。
- **证据引用 `EvidenceRef`**：`TimelineEvent.evidence: EvidenceRef[]`，每条时间线事件可关联一个或多个证据（id/sourceType/sourcePath/rawKey/description/confidence/relatedEventId），confirmed 事件可追溯具体证据，inferred 记录推断依据；不复制整段原始存档文本。
- **头衔模型（Phase 2B M3 新增）**：`TitlePeriod`（titleId/name/tier/start/end/isCurrent/government/sourcePath）、`TitleTier`（`Enum`：barony/county/duchy/kingdom/empire/unknown）；`CharacterProfile.titles: TitlePeriod[]`、`CharacterSummary.primaryTitle/highestTitleTier/isRuler`。TS（`types.ts`）与 Python（`models.py`）严格同步；TS 联合类型在 Python 用 `Enum`（`str, Enum`）表达，运行时拒绝非法字符串。
- **关系与记忆模型（Phase 2B M4 新增）**：`RelationshipType` 增 `betrothed` / `concubine`（TS 联合 + Python `Enum` 严格镜像）、`RelationshipPeriod.isFormer?: boolean`（former_spouses / former_concubines 等存档直述前任）；`CharacterProfile.memories: LifeEvent[]`（记忆原始条目，`EvidenceRef.sourceType="memory"`）、`friends/rivals/lovers: CharacterRef[]`（became_* 记忆 date-pairing 推断，标 `inferred`）、`siblings: CharacterRef[]`（共享父母推导，`sourcePath` 带 `#inferred_from_shared_parent`）。`MemoryTimelineIndex` 将记忆归属到人物：married/child_born 用 family_data 交叉引用（owner 为全局计数器不可解码）、battle/war/*_died 用 subject 角色、无日期记忆只入原始列表不生成事件。TS（`types.ts`）与 Python（`models.py`）严格同步。
- **时间线去重合并（Phase 2B M5 新增，M5.1 加固）**：`TimelineEvent.mergedCount?: number`（>1 表示该事件由 N 条重复存档记录合并，前端据此显示「已合并 N 条记录」徽标）。合并逻辑在 `apps/server/app/services/timeline_builder.py` 的 `merge_timeline(events)` 纯函数：去重键 `(type, date, 首位可靠实体锚点)`，锚点优先级 `relatedCharacters[0].id → relatedTitles[0].id → location.id`；**无日期或无可靠实体锚点的事件永不合并**（M5.1：禁止用 description/title/空字符串/数组位置做去重依据，防止同日同类不同事件误并）；保留 id 最小事件为主，`evidence` 按 id 聚合（合并组中 0 缺证据保持 0），`mergedCount=组大小`，返回 `TimelineMergeResult(timeline, merged_count, merge_details)`。`to_profile` 的基础/头衔/记忆三来源统一走 merge（替换原三处 `extend`+sort）。根因：真实存档中 child_born + first_born/twins_born 是同一孩子同日的双记忆（400 人抽样 43 人 ≈11%），合并后同键重复 0。
- **人物引用解析状态（Phase 2B M5.1 新增）**：`CharacterRef.resolved?: boolean` —— true 表示姓名已从人物索引/本地化数据得到可读名；false/缺省表示仅保留原始人物 id 或内部 key，**不得当作真实姓名写入 LLM 摘要**（与关系事实的 `confidence` 无关：父母可由 child_backref 推断，但名字仍可解析）。父母/子女/兄弟姐妹/好友/宿敌/恋人统一经 `character_extractor._character_ref_for`（by_id 人物索引 + `resolve_display_name` + `resolved` 如实标注 + 按 id 去重）构建；`memory_timeline_extractor._char_ref` 同步标注。LLM 输入过滤纯函数 `sanitize_character_ref_for_llm`（`apps/server/app/services/llm_input_filter.py`）：`resolved=false` 且 name 为纯数字 → 不写入自然语言摘要，保留 id 内部追踪，不编造占位姓名。真实存档抽样 500 人 1296 条人物引用中**纯数字占位名 0 条**。
- **`BiographyChapterOutline` / `BiographyChapter` 的 `eventIds` 非空**：Python 侧运行时校验（Pydantic `min_length=1` + validator），每章必须至少引用一个时间线事件。
- **Mock 包裹层 `FixtureEnvelope<T>` / `MockDataset`**：测试/Mock 数据用包裹结构（`isMock: true`、`source: "fixtures/mock"`、`schemaVersion`、`generatedFor`、`data`），Mock 元数据与真实 `CharacterProfile` 等严格隔离，绝不污染业务模型。
- **集合字段安全默认**：Python 侧所有列表/字典字段均 `default_factory=list/dict`，TS 侧数组字段为必填（由调用方填充）。

契约运行时校验见 `packages/save-schema/py/tests/test_contract.py`（pytest），TS 侧通过 `tsconfig.json` 严格模式（`tsc --strict --noEmit`）校验。

### 3.2 前端架构（Phase 1A 起）

前端（`apps/web`）是契约的消费者，不直接依赖解析库内部结构：

- **技术栈**：Vite 5 + React 18 + TypeScript（strict）+ Tailwind 3（东方数字史馆：paper/ink/cinnabar/gold/jade/indigo 通道化 Design Token，系统字体回退，不下载不提交字体）+ Zustand 4（状态）+ Framer Motion 11（仅必要过渡，统一 `MotionConfig reducedMotion="user"`）+ ESLint 8（typescript-eslint + react + react-hooks + jsx-a11y）。
- **契约接入**：通过 `vite.config.ts` 的 `@shiguan/save-schema` 别名直接消费 `packages/save-schema/src/types.ts`（TS 事实来源），不另起一份类型；Mock 数据通过 `@mock` 别名从 `fixtures/mock` 载入。
- **数据流**：`loadMock` 把 `FixtureEnvelope<MockDataset>` 转为 `ParsedSave`（`characterIndex` 摘要 → 选择页；`profiles` 按需完整档案 → 传记页）；`buildDraft` 从时间线确定性生成章节提纲，每章 `eventIds` 来自真实事件。
- **页面**：起始页（拖拽上传区 + 隐私说明）→ 解析过程页（真实分阶段状态）→ 人物选择页（搜索/筛选/摘要卡片）→ 人物传记页（桌面三栏：时间线 / 章节正文 / 史料依据面板；移动端单栏重排：正文 `order-1` 置顶 → 时间线 `order-2` → 史料 `order-3`，渲染 `EvidenceRef` 与不确定提示，滚动同步高亮）。
- **PWA 骨架**：`manifest.webmanifest` + `sw.js`（显式静态资源白名单，仅缓存 shell 与 `/assets/`，绝不缓存 `/api/`、`/uploads/`、`/saves/`、带 `Authorization` 的请求或私有数据；`sw.js` 为源码随仓库发布，`dist/` 为构建产物仍忽略）。

---

## 4. 存档解析架构（最关键的风险点）

### 4.1 适配器协议

```python
from pathlib import Path
from typing import Protocol
from packages.save_schema.py.models import SaveInspection, ParsedSave

class SaveParserAdapter(Protocol):
    def inspect(self, path: Path) -> SaveInspection:
        """只判断文件类型/编码/是否需要外部组件，不解析内容。"""
        ...

    def parse(self, path: Path) -> ParsedSave:
        """产出标准索引与人物档案。失败必须抛出明确异常。"""
        ...
```

### 4.2 两条解析路线（Phase 0 决策）

| 路线 | 适用输入 | 实现 | 许可证 | 备注 |
|---|---|---|---|---|
| **A. 自研 Python PDX 文本解析器** | `text`（调试明文 / 解压后 gamestate / 纯文本存档）、`text_zip`（标准 .ck3 解压后） | 自研、可测试 | 自有代码 | 规范仅禁止"从零写无法维护的**二进制**解析器"。明文 Clausewitz 格式稳定，是可控可维护的子集。 |
| **B. Rakaly CLI 适配器** | `binary_zip` / `binary` / `ironman`（二进制与铁人） | 外部二进制 `rakaly` 融化(melt)为明文，再走路线 A | Rakaly 本体 MIT（需部署时核实具体许可） | 缺失时**显式报错 + 安装提示**，绝不静默失败/伪造。 |

**为什么不让 jomini 直接进后端**：jomini 最佳绑定是 Rust 与 JS/WASM，没有官方 Python 绑定；引入它需要额外运行时（Node 或 Rust 编译），与"Python 后端"冲突。故 jomini 仅作为**备选**记录（见 save-format-notes.md），当前不纳入主链路。

**为什么铁人存档不能"免费"本地解码**：铁人解码需要 TokenResolver（令牌表），按 PDS 协议要求**不能随开源库分发**，也不能在文档里公开推导方法。因此：
- 本地解码铁人 = 用户自行提供令牌表文件（`RAKALY_IRONMAN_TOKENS_PATH`），由 Rakaly CLI 使用；
- 若用户无令牌表且显式开启远程，可用 Rakaly 在线服务，但必须给出明确隐私警告（数据离开本地）；
- 二者皆不具备时，解析阶段直接报错，绝不假装成功。

### 4.3 输入类型自动判断

`inspect()` 依据文件特征判定 `SaveKind`：
- 含 ZIP 签名（文件尾部 EOCD）→ 解压后看头字节：`01 00` 为 ironman，否则为标准 `text_zip`（明文头）或 `binary_zip`（二进制头）。
- 无 ZIP 签名 → 自动存档的未压缩 gamestate：`text`（可 UTF-8 解码且含 `CK3txt`/Clausewitz 结构）或 `binary`。
- 编码：CK3 用 UTF-8（与 EU4 的 Windows-1252 不同），需据此正确解码。

---

## 5. 隐私与安全架构

- 存档默认只在本地后端解析，不离开机器。
- 远程模型需 `LLM_ALLOW_REMOTE=true` 显式开启；开启前 UI 必须弹明确提示："人物档案中的部分数据将发送至所配置的模型服务。"
- 发送给模型的是**压缩后的结构化人物档案**，不是完整存档。
- 禁止：日志输出 API Key、上传存档到未知服务、默认遥测、未提示发送完整存档、把大型存档永久放入浏览器缓存、提交真实存档或密钥到 Git。
- `.env` 已被 gitignore；`.env.example` 不含任何真实密钥。

---

## 6. PWA 与移动端架构（Phase 4 完善）

- 提供 `manifest.webmanifest` 与离线壳（service worker 缓存静态资源）。
- **不缓存**敏感存档或 API Key。
- 大型存档解析主要在电脑后端完成；手机通过局域网访问电脑服务浏览已解析人物。
- 不依赖 Android Studio / Gradle / 原生 Android 工程。
- 传记页移动端改为单栏，禁止把桌面三栏简单缩小。

---

## 7. 工程与测试约定

- 修改 Python 后：`python -m py_compile` + 相关 pytest。
- 修改 TS/JS 后：`tsc --noEmit` + eslint + `vite build`。
- 测试至少覆盖：解析（无效/空/压缩/纯文本/不支持二进制/缺解析器/非 UTF-8/超大/重复键）、人物数据（活人/死者/多次婚姻/多头衔/无头衔/无地点/缺日期/关系循环/同名）、传记（时间倒置/推断当事实/虚构配偶头衔/无证据对白/每章关联事件/非法 JSON 重试）、前端（上传/错误反馈/搜索/时间线交互/移动端/键盘/长文性能）。
- 测试失败必须修复或回滚，不留明显无法启动的状态。
- 默认不提交 Git，除非本轮明确要求。

---

## 8. 当前进度（Phase 0.5 + 1A + 1B + 1C + 1C.1 + 2A + 2A.1 + 2B M1–M5 + M5.1 + 3A，均已完成）

- ✅ 目录结构（最小、非空）
- ✅ 数据契约：`packages/save-schema/src/types.ts` + `py/models.py`，Phase 0.5 已补齐并严格同步
  - ✅ Python 补齐 `SaveKind` / `Encoding` / `MissingComponent` / `SaveInspection` / `ParsedSaveMeta` / `ParsedSave`
  - ✅ TS/Python 严格镜像：`RelationshipType` / `WarRole` / `FactCheckStatus` / `Encoding` 用 Enum 约束，运行时拒绝非法值
  - ✅ 新增 `CharacterSummary` / `CharacterIndexEntry`、`EvidenceRef`、`FixtureEnvelope<T>` / `MockDataset`
  - ✅ `ParsedSave` 分离 `characterIndex`（摘要）与 `profiles`（按需完整档案）
  - ✅ `BiographyChapterOutline` / `BiographyChapter` 的 `eventIds` 非空运行时校验
- ✅ 四份文档：`architecture.md` / `save-format-notes.md` / `biography-pipeline.md` / `roadmap.md`
- ✅ `.env.example`（无真实密钥）、`.gitignore`、`README.md`、`AGENTS.md`
- ✅ `fixtures/mock/README.md` 同步 FixtureEnvelope/MockDataset 契约
- ✅ 验证：`py_compile` 通过、pytest 19 项通过、TS 严格类型检查通过
- ❌ 未实现任何解析器（Phase 0/0.5 均不写虚假完整解析器）
- ❌ 未搭建后端骨架（留给 Phase 2）

**Phase 1A（前端工程骨架）已完成**：`apps/web` 已建立（Vite+React+TS strict+Tailwind+Zustand+Framer Motion），四页面壳 + Mock 数据（FixtureEnvelope 包裹）+ Zustand 状态 + 确定性章节提纲 + PWA 骨架；`tsc --strict` 与 `vite build` 均通过。详见 `roadmap.md` 与本文 3.2 节。

**Phase 1B（纵向流程与状态管理打磨）已完成**：索引/档案按需加载（`index.json` + `profiles/<id>.json`，经 `import.meta.glob(eager:false)` 懒加载）；`validateProfileEnvelope` 运行时契约校验（不依赖 TS 断言，修复了返回包裹而非档案本体的真实 bug）；基于 History API + `useSyncExternalStore` 的可靠路由（修复 popstate 不重读 location 的真实 bug，前进/后退与 `navigate()` 均正确驱动 `useRoute`）；传记页时间线↔章节正文双向滚动同步（IntersectionObserver + 滚动锁，尊重 `prefers-reduced-motion` / 移动端）；史料依据面板仅高亮当前事件告警；`MockParseService` 确定性分阶段状态机（pending→running→success/error，支持 AbortController 取消与 failAt 注入）；边界场景（多次婚姻/多头衔/无头衔/地点无法定位/日期缺失稳定排序/推断事件）覆盖并测试；`sw.js` 重写为显式静态白名单（绝不缓存 `/api/`、`/uploads/`、`/saves/`、带 `Authorization` 的请求、非 GET、跨域或私有数据），`sw.js` 纳入版本库、`dist/` 仍忽略；Vitest + RTL + jsdom 共 32 项测试通过。详见 `roadmap.md`。

**Phase 1C（响应式 · 无障碍 · 视觉定稿 · PWA 收尾）已完成**：东方数字史馆设计语言定稿（通道化 Design Token + 系统字体回退 + 共享组件库 MuseumSurface/ScrollPanel/SealButton/InkDivider/PortraitFrame/EvidenceBadge/TimelineNode/PageHeading/EmptyState/AssetImage/icons + 四页面改造）；键盘可达性（skip-link / 路由切换焦点管理 / 44px 触控）、移动端单栏重排（正文 `order-1` 置顶 → 时间线 `order-2` → 史料 `order-3`）、Framer Motion `MotionConfig reducedMotion="user"` + CSS 媒体查询双重 reduced-motion；加载竞态修复（按人物的 `profileRequestStateById` + `requestId`）；`/design-lab` 视觉实验室；PWA 缓存策略抽离为可单测纯函数 `swCachePolicy.ts`；ESLint 8 链路（`npm run lint` / `lint:fix`）；Vitest 前端测试 66 项。详见 `roadmap.md`。

**Phase 1C.1（验收修复与视觉收口）已完成**：补齐 `BiographyPage.test.tsx`（12 项，全量 Vitest **96 项**）、`swHandler.ts` 可测试离线导航 handler（13 项）；路由无障碍（title 随路由含人物名、切换人物焦点重入 main）；克制动效（墨线延伸 / 朱砂落印 / 时间线脉冲 / 章节 `whileInView` 淡入 / EvidencePanel 交叉淡入，reduced-motion 双重降级）；东方素材 WebP 化（PNG 约 6.49 MB → WebP 约 1.11 MB，CSS `image-set` 回退）并移出 4 张参考图至 `docs/design-reference/`；`ParsePage` 移除 eslint-disable 改 `useCallback` 并修 `exhaustive-deps`（`npm run lint` 零错误零警告）；清理临时产物 + 补 `.gitignore`；建立 `docs/ASSET_AUDIT.md` 素材审计表；经用户授权推送到公开远端。详见 `roadmap.md`。

**Phase 2A（本地 CK3 存档库 · 解析器评估 · Mod 感知解析 MVP）已完成**：`tools/ck3-reader` Rust sidecar（ck3save 0.4.3 + jomini，MIT）melt 真实二进制 SAV0101；FastAPI 后端（`adapters/` `services/` `routers/saves.py`）；本地存档自动发现（Windows Known Folder，不硬编码）；目录监听（写入中不解析，`wait_until_stable`）；Mod 兼容报告；人物索引与按需 Profile（一次 melt、多次查询，`data/cache/<saveId>/<signature>/`）；前端双模式（后端不可用回退 Mock）。详见 `docs/phase2a-report.md`、`docs/parser-evaluation.md`。

**Phase 2A.1（真实路由分页 / CI / 安全导入）已完成**：`POST /api/local-saves/import` 安全导入（净化文件名防路径穿越）；前端 `/saves/:saveId/characters` 真实分页路由（首屏一页、防抖搜索、取消过期请求）；GitHub Actions CI 四作业。详见 `docs/phase2a1-report.md`。

**Phase 2B M1–M5（真实人物语义深化）已完成**：M1 反推真实 token + 重写 `scan_characters_full`（三容器 44096 人物）+ 字段真值；M2 实体索引 10 类 + `ReferenceResolver` 诚实解析 + `GET /local-saves/{id}/entities`；M3 头衔与统治经历 —— Rust `scan_titles`（19003 条，`titles.json`，Format A/B 双格式）、Python `TitleReignExtractor`/`TitleProfileIndex`（5230 名现任统治者、7423 人有头衔记录、`GET /local-saves/{id}/characters/{cid}/titles`）、`CharacterProfile.titles` + `title_gain`/`title_loss`/`succession` 时间线事件（全部带 EvidenceRef）、`CharacterSummary.primaryTitle/highestTitleTier/isRuler`、真实 token 表下中文头衔（`教宗国`/`幽蓟`/`拜占庭帝国`）。M3 连带修复：M2 误删 parse 路由装饰器（补回 + 路由注册表测试）、`game_version` 整词匹配、缓存 `reader_version` 门槛 + **二进制指纹门禁**（占位/真实 token 表构建互不复用缓存）。M4 关系与记忆深化 —— Rust `scan_memories`（`memories.json`：28675 条 / 116 类型，participants 角色表 / dates / battle_location）+ `scan_characters_full` 增 6 婚姻历史字段（former_spouses/betrothed/concubine/concubinist/former_concubinists/former_concubines）、Python `MemoryTimelineIndex`（主体角色归属表 → `CharacterProfile.memories` + 时间线事件 + became_* date-pairing 推断关系 + 告警，名字经会话记录解析非裸 id）、`GET /local-saves/{id}/characters/{cid}/memories`、前端 `MemoriesPanel`（关系 chips + 记忆列表 + 空态）。详见 `docs/phase2b-m3-report.md`、`docs/phase2b-m4-report.md`。
**Phase 2B M5（时间线去重合并 + 搜索/导入/人名中文化）已完成**：契约 `TimelineEvent.mergedCount` 双端同步 + 契约测试；`timeline_builder.py` 的 `merge_timeline` 纯函数（去重键 `(type, date, 首位 related id)`、无日期不合并、证据聚合 0 缺证据、`mergedCount=组大小`）；`to_profile` 基础/头衔/记忆三来源统一去重合并；`GET /local-saves/{id}/characters/{cid}/timeline`（返回 eventCount/mergedCount/mergeDetails/timeline）；**搜索修复**（`q` 匹配解析后字段：名字经 `loader.resolve` + 头衔名 + 王朝/文化/信仰名，模块级 LRU 缓存 name key→解析名；`title=` 按头衔名反查 holder id 集合过滤）；**loader 缺失重建**（重启/直达 URL 后名字仍中文）；**人名中文化**（loc key→本地化表 / 拼音hex `Zhongrong_4EF2_5BB9`→Unicode 解码「仲容」/ 拉丁名 `Maurizio`→游戏 `character_names_l_simp_chinese.yml`「毛里齐奥」，`names/` 子目录确认被 `**/*.yml` 覆盖）；前端 `RealParsePage`（真实后端 3 阶段：初检 inspect→Mod 报告→melt 解析，失败重试，成功落印进选择页）+ `TimelineNode` 合并徽标 + `api.getTimeline`。详见 `docs/phase2b-m5-report.md`。
**Phase 2B M5.1（LLM 前数据完整性收口）已完成**：① 无实体锚点事件不再误合并（`_dedup_key` 无锚点返回 None，仅同 type+date+同可靠锚点才合并，新增 6 项去重安全测试）；② `CharacterRef.resolved` 双端契约（TS+Python+契约 roundtrip + mock fixtures 标注 `resolved:true`）+ 统一引用构建（`_character_ref_for`：父母/子女/兄弟姐妹/好友/宿敌/恋人 by_id+loader 解析，unresolved→原 id+resolved=False，列表按 id 去重；`memory_timeline_extractor._char_ref` 同步）；③ LLM 输入过滤 `sanitize_character_ref_for_llm`（resolved=false 且数字名不写入摘要）；④ 前端 `contractValidate` 补 CharacterRef 运行时结构校验。真实存档抽样 500 人：名字中文 58.2%、人物引用 1296 条中**纯数字占位名 0 条**、已解析 42.3%（其余为本地化未命中的内部 key，如实标 resolved=False 不伪造）。

**Phase 3A（本地优先传记提纲生成管线）已完成**：新增 `packages/biography-engine/py`（与 server 同仓共享 sys.path）——

- **Provider 抽象**（`providers/base.py`）：`LlmProvider` Protocol（`health` / `generate_json`）；`ProviderError` 家族六种错误码（`provider_not_configured` / `provider_unreachable` / `remote_provider_disabled` / `provider_timeout` / `invalid_model_output` / `provider_error`）。
- **OpenAICompatibleProvider**（`providers/openai_compatible.py`）：调用 `{base_url}/chat/completions`；默认本地 `http://127.0.0.1:8080/v1`，非本地地址在 `LLM_ALLOW_REMOTE=false` 时直接拒绝；`_extract_json` 剥 code fence/前后解释文字；`redact_base_url` 只暴露 `scheme://host:port`；健康检查发最小 ping。
- **FakeLlmProvider**（`providers/fake.py`）：脚本化（json/raw/invalid_json/timeout/unreachable/error），CI 与演示全用它。
- **配置**（`config.py`）：仅读环境变量（不覆盖 `.env`）；`provider_config` 做类型转换与非法回退。
- **确定性压缩**（`compressor.py` + `importance.py` + `models.py`）：`compress_profile` → `CompressedProfile`（`COMPRESSION_VERSION="1"`）；`score_event` 分解（类型/confidence/证据数/合并数/日期/最高头衔 tier 加权/未解析实体降权）；`_select_events` 强制保留出生/死亡/最高头衔事件 + 每十年阶段代表 + 名额择优，受 `max_events` 硬上限；unresolved 数字人物名不进入自然语言摘要（`llm_input_filter.sanitize_character_ref_for_llm`）。**日期必须 `_date_key` 数值比较**（复用 `title_reign_extractor`）：CK3 日期未零填充，`944.10.22` 字符串排序会排在 `944.4.20` 之前导致时间倒置。
- **版本化 Prompt**（`prompt_builder.py` + `prompts/outline.zh-Hans.v1.txt`）：`PROMPT_VERSION="outline.zh-Hans.v1"`；user_prompt 只含压缩档案 + style + `OUTLINE_JSON_SCHEMA`，绝不泄漏绝对路径/API Key/令牌表。
- **提纲生成**（`outline_generator.py` + `validators.py`）：`validate_outline`（章节数 1–10、章节 id 唯一、eventIds 非空且来自白名单、章节时间大致有序）；`OutlineGenerator` 原始 1 次 + 修复 `DEFAULT_MAX_REPAIR=1` 次（Provider 输出解析失败与校验失败均可触发修复；超时/不可达/未配置为终态）；非法输出不进保存。
- **后端 API**：`GET /api/llm/health`（`routers/llm.py`，脱敏：configured/provider/baseUrlRedacted/model/local/reachable/errorCode）；`POST /api/local-saves/{id}/characters/{cid}/biography/outline` + `GET .../biography/outlines`（`routers/saves.py`）；`services/outline_store.py` SQLite 记录（`data/biography-outlines.sqlite`：save_id/save_signature/character_id/style/status/outline_json/error_*/retry_count/warnings/compression_version/prompt_version/created_at，签名变化 → `stale=true`）。
- **前端**：`OutlinePanel`（真实模式；模型健康状态 / 文风·事件上限·推断/存疑开关 / 点「生成提纲」才调用，打开页面不自动生成 / 章节展示 / 按 errorCode 给可操作提示）；`api.ts` 增 `getLlmHealth` / `generateOutline` / `listOutlines`。

详见 `docs/phase3a-report.md`。
