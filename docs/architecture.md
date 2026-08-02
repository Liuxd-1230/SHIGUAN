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

## 8. 当前进度（Phase 0.5 数据契约收口 + Phase 1A 工程骨架已完成）

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

下一轮（Phase 2）见 `roadmap.md`。
