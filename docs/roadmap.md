# 史官 SHIGUAN —— 开发路线图

本文档跟踪各 Phase 的范围、当前进度与下一轮建议。每轮工作完成后更新。

---

## Phase 0 —— 研究与架构（✅ 本轮已完成）

**目标**：确立技术路线、设计数据契约、产出架构文档，不写虚假完整解析器，不堆砌复杂动画。

完成项：
- ✅ 检查项目目录（为空，无 Git 历史）。
- ✅ 调研并对比至少两种解析路线（Rakaly/jomini/ck3save vs 自研 Python PDX 文本解析器；另记录 ck3-savetools、jomini JS/WASM、scorpdx 等）。
- ✅ 记录普通/压缩/二进制/铁人存档的处理矩阵与铁人令牌限制。
- ✅ 设计 `CharacterProfile`、`TimelineEvent`、证据模型（`EvidenceWarning`、`confidence`）并落地为 `packages/save-schema/src/types.ts` + `py/models.py`。
- ✅ 编写 `docs/architecture.md`、`docs/save-format-notes.md`、`docs/biography-pipeline.md`、`docs/roadmap.md`。
- ✅ 建立 `.env.example`（无真实密钥）、`.gitignore`、`README.md`、`AGENTS.md`。
- ✅ `fixtures/mock/README.md` 定义 Phase 1 的 Mock 数据契约。
- ✅ 运行可用检查：Python `py_compile` 通过（见末节验证结果）。

未做（刻意为之）：
- ❌ 未实现任何解析器（规范禁止 Phase 0 写虚假完整解析器）。
- ❌ 未搭建前端/后端骨架（留给 Phase 1/2）。

---

## Phase 0.5 —— 数据契约收口（✅ 本轮已完成）

**目标**：在不动页面、不动解析器的前提下，把 TS/Python 数据契约收口到可进入 Phase 1A 的扎实状态。

完成项：
- ✅ TS/Python 严格同步：Python 补齐 `SaveKind` / `Encoding` / `MissingComponent` / `SaveInspection` / `ParsedSaveMeta` / `ParsedSave`；所有 TS 联合类型在 Python 用 Enum 严格约束（`RelationshipType` / `WarRole` / `FactCheckStatus` / `Encoding`），运行时拒绝非法字符串。
- ✅ 人物列表摘要模型 `CharacterSummary` / `CharacterIndexEntry`（id/name/sex/生卒/王朝/文化/信仰/主要头衔/最高头衔等级/是否统治者/是否在世/是否玩家王朝/肖像 key/证据告警计数）。
- ✅ `ParsedSave` 重构：`characterIndex`（轻量摘要，供选择页）与 `profiles`（按需完整档案）分离，避免大型存档一次性生成全部完整 Profile。
- ✅ 证据引用模型 `EvidenceRef`，`TimelineEvent.evidence: EvidenceRef[]` 关联一个或多个证据；confirmed/inferred 均须可追溯依据，不复制整段原始存档文本。
- ✅ Mock 包裹层 `FixtureEnvelope<T>` / `MockDataset`（`isMock` / `source` / `schemaVersion` / `generatedFor` / `data`），Mock 元数据与真实 `CharacterProfile` 严格隔离。
- ✅ 结构约束强化：`BiographyChapterOutline` / `BiographyChapter` 的 `eventIds` 非空（运行时校验）；集合字段安全默认；TS/Python 字段名一致。
- ✅ 契约测试：`py/tests/test_contract.py`（19 项 pytest）覆盖非法枚举拒绝、空 eventIds 拒绝、序列化往返、SaveInspection/ParsedSave 生成、Mock 包裹分离、JSON fixture 读取；TS `tsconfig.json` 严格模式 `tsc --strict --noEmit` 通过。
- ✅ 文档同步：`architecture.md` / `roadmap.md` / `fixtures/mock/README.md` / `AGENTS.md` / `README.md`。

本轮明确不做：CK3 真实解析、FastAPI 后端、LLM 调用、完整前端页面、PWA、视觉设计、git push。

---

## Phase 1A —— 工程骨架 · Mock · 核心页面壳（下一轮建议）

**目标**：建立前端工程骨架，落地带 `FixtureEnvelope` 包裹的 Mock 数据，跑通"选人 → 看传记 → 看时间线 → 看证据"的最小纵向链路。

范围：
1. 初始化 `apps/web`（Vite + React + TS + Tailwind + Zustand + Framer Motion + PWA 骨架），接入 `packages/save-schema` 的 TS 契约。
2. 在 `fixtures/mock/` 落地 1–2 份**明确标注为非真实解析**的数据，全部用 `FixtureEnvelope` 包裹（`isMock: true`），内部为 `CharacterProfile` + `TimelineEvent`（含 confirmed/inferred/uncertain 三种证据）。
3. 人物选择页：消费 `ParsedSave.characterIndex`（`CharacterSummary[]`）做搜索/筛选/卡片摘要。
4. 人物传记页（桌面三栏 + 移动端单栏）：章节式正文、可缩放时间线、史料依据面板（渲染 `EvidenceRef`）、不确定提示、滚动同步高亮。
5. 起始页（深酒红/骨白/暗金/炭黑克制配色，拖拽上传区，隐私说明）与存档解析过程页（阶段状态来自 Mock 任务状态，非假进度条）。

验收：能离线用 Mock 数据完整走通"选人 → 看传记 → 看时间线 → 看证据"。

### Phase 1A 完成情况（✅ 本轮已完成）

- ✅ 工程骨架：`apps/web`（Vite 5 + React 18 + TS 5 strict + Tailwind 3 + Zustand 4 + Framer Motion 11），目录布局见 architecture.md。
- ✅ 契约接入：通过 `@shiguan/save-schema` 别名直接消费 `packages/save-schema/src/types.ts`（TS 事实来源），未另起一份类型。
- ✅ Mock 数据：`scripts/gen_mock.py` 复用 pydantic 契约生成 `fixtures/mock/{arnulf,lowborn,index}.json`，全部用 `FixtureEnvelope` 包裹（`isMock:true`），覆盖三类证据、多次婚姻、多头衔、无头衔、推断/不确定、EvidenceRef。
- ✅ 起始页（拖拽上传区 + 隐私说明）、解析过程页（真实分阶段状态，非假进度条）、人物选择页（搜索/筛选/CharacterSummary 卡片）、人物传记页（lg 三栏 + 移动单栏：时间线 / 章节正文 / 史料依据面板，渲染 EvidenceRef，不确定提示，滚动同步高亮）。
- ✅ 状态管理：Zustand 持有 ParsedSave（characterIndex 摘要 + profiles 按需档案）、视图路由、选中人物、搜索/筛选。
- ✅ 从时间线确定性生成章节提纲（`buildDraft`，每章 eventIds 非空且来自真实事件），明确标注"非 AI 生成"。
- ✅ PWA 骨架：`manifest.webmanifest` + 最小 `sw.js`（仅缓存同源静态，不缓存敏感数据）。
- ✅ 验证：`tsc --strict --noEmit` 通过；`vite build` 通过（413 模块，Mock JSON 已打包）。
- ⚠️ 未做：eslint 链路、完整视觉定稿、移动端深度适配与无障碍审计、真实解析/后端/LLM（留待 1B/1C 与 Phase 2/3）。

---

## Phase 1B —— 纵向流程与状态管理打磨（✅ 本轮已完成）

**目标**：把 Mock 数据流与全局状态（Zustand）打通，确保选择页、传记页、时间线、证据面板的联动正确，并妥善处理边界场景。

范围（已全部落地）：
1. 全局状态：`currentSave`（ParsedSave 的 Mock 实例）、`selectedCharacterId`、筛选条件。
2. 选择页 → 传记页的路由与按需取档（从 `profiles[id]` 取完整档案，而非一次性加载全部）。
3. 边界场景演示：多次婚姻、多头衔、无头衔、地点无法定位、日期缺失、推断事件。
4. 史料依据面板与时间线联动、不确定信息提示的视觉规范。

### Phase 1B 完成情况（✅ 本轮已完成）

- ✅ 索引/档案按需加载：`index.json`（`MockIndex`：meta + `characterIndex` + `profileIds`）+ `profiles/<id>.json`（`FixtureEnvelope<CharacterProfile>`）；完整档案经 `import.meta.glob(eager:false)` 懒加载，选择页只持摘要，进入传记页才取完整档案，不一次性加载全部。
- ✅ 运行时契约校验：`validateProfileEnvelope` 在载入时校验 `isMock===true`、`source==="fixtures/mock"`、`schemaVersion`、数组字段、`profile.id` 与包裹一致、`confidence∈{confirmed,inferred,uncertain}`、`evidence` 数组；不依赖 TS 断言。修复了「返回包裹而非档案本体」的真实 bug（`CharacterProfile` 字段此前为 `undefined`）。
- ✅ 可靠路由：`router.tsx` 基于 History API + `useSyncExternalStore` + popstate + 自定义 `NAV_EVENT`，无 react-router。`navigate()` 与浏览器前进/后退均正确驱动 `useRoute`。（修复了 popstate 订阅不重读 `location` 的真实 bug——后退/前进曾停留在旧视图。）
- ✅ 双向滚动同步：传记页「时间线 ↔ 章节正文」用 IntersectionObserver 互相高亮，配 700ms 滚动锁防抖；尊重 `prefers-reduced-motion` 与移动端（移动端关闭同步，改单栏）。
- ✅ 史料依据面板：`EvidencePanel` 仅高亮与「当前事件」相关的 `EvidenceRef` 告警；来源类型中文标签（`save_block`→存档数据块）；来源路径缺失 / 无事件时给出明确提示，绝不静默。
- ✅ 确定性解析状态机：`MockParseService` 分阶段（pending→running→success/error），固定延时、无 `Math.random`、可 `AbortController` 取消、`failAt` 注入失败；解析过程页状态来自真实任务状态，非假进度条。
- ✅ 边界场景：多次婚姻、多头衔、无头衔、地点无法定位、日期缺失（year 0 稳定排在同章有日期事件之前）、推断/不确定事件——均在前端演示并由测试覆盖。
- ✅ PWA 安全缓存：`sw.js` 重写为显式静态白名单（shell + `/assets/`），绝不缓存 `/api/`、`/uploads/`、`/saves/`、带 `Authorization` 的请求、非 GET、跨域或私有数据响应；`activate` 清理过期缓存。已从 `.gitignore` 移除 `apps/web/public/sw.js`（源码须随仓库发布），保留忽略 `apps/web/dist/`。
- ✅ 前端测试：Vitest + RTL + jsdom，共 **32 项通过**（27 新增 + 5 原有），覆盖解析状态机、提纲生成、路由、契约校验、选择页搜索/筛选、证据面板高亮等 ≥12 项非快照断言；`src/test/setup.ts` 桩接 IntersectionObserver/matchMedia/scrollIntoView。
- ✅ 验证：`py_compile` 通过、pytest 19 项通过、`save-schema tsc` 通过、`web tsc --noEmit` 通过、Vitest 32 项通过、`vite build` 通过（421 模块）。
- ⚠️ 未做（遗留，交 Phase 1C）：eslint 链路、移动端深度适配与无障碍审计、视觉语言定稿、真实解析/后端/LLM。

---

## Phase 1C —— 响应式 · 无障碍 · 视觉定稿 · PWA 收尾

**目标**：补齐移动端深度适配与无障碍审计，定稿视觉语言，收尾 PWA 离线体验。

> 说明：前端测试与 PWA 安全缓存已在 Phase 1B 提前完成（Vitest 32 项、sw.js 显式白名单），故 1C 不再重复这两项，聚焦响应式 / 无障碍 / 视觉。

范围：
1. 移动端单栏布局深度适配、键盘可达性、对比度、`prefers-reduced-motion`、无障碍审计（ARIA / 焦点管理 / 读屏）。
2. 补充测试覆盖：上传 / 错误反馈 / 移动端 / 键盘 / 长文性能（1B 已覆盖解析状态机 / 提纲 / 路由 / 契约 / 选择页 / 证据面板）。
3. PWA：离线壳可达性验证、首次加载与更新流程、不缓存敏感存档/密钥（安全缓存策略已定，1C 做体验收尾）。
4. 视觉语言定稿（东方数字史馆：paper / ink / cinnabar / gold / jade / indigo 通道化 Design Token + 系统字体回退，不下载不提交字体）。

---

### Phase 1C 完成情况（✅ 本轮已完成）

- ✅ 东方数字史馆设计语言定稿：`index.css` 全量通道化 Design Token（paper/ink/cinnabar/gold/jade/indigo + 语义色 confirmed/inferred/uncertain/danger + motion/ease）、light 主题、`paper-grain`/`hero-mountain` 工具类、reduced-motion 媒体查询；`tailwind.config.js` 接入全部 token 与新字体、4 个 keyframe（fade-in-up / seal-stamp / ink-draw / slow-spin）。
- ✅ 共享组件库（10 个）：`MuseumSurface`（raised/inset/flat）、`ScrollPanel`、`SealButton`（primary/secondary/danger/ghost，`min-h-[2.75rem]`）、`InkDivider`（line/dotted/seal，带 label 时以 `role="separator"`+`aria-label` 暴露）、`PortraitFrame`（图失败退化为首字朱砂印，文化不臆造）、`EvidenceBadge`（图标+形状+文字三重表达替代 color-only）、`TimelineNode`（aria-current/aria-pressed）、`PageHeading`、`EmptyState`、`AssetImage`（装饰图失败 `return null` 优雅降级）；16 个内联 SVG `icons`（均 aria-hidden + currentColor）。旧 color-only `ConfidenceBadge` 退役。
- ✅ 四页面视觉改造：起始页（山水意象 + 落印动画 + 视觉实验室入口）、解析页（emoji→图标 `StatusIcon`、错误详情深色 `pre`）、选择页（系统字体、accent 勾选）、传记页（三栏 `order` 响应式 + `PortraitFrame` + `MuseumSurface` + `ScrollPanel` + `SealButton` + `InkDivider` + 密度切换 `aria-pressed`）。
- ✅ 动效与 reduced-motion：Framer Motion `MotionConfig reducedMotion="user"` + CSS `@media (prefers-reduced-motion: reduce)` 双重降级；`seal-stamp` 为全站唯一仪式性主动画，每页至多一个。
- ✅ 加载竞态修复：`store.ts` 改为按人物的 `profileRequestStateById: Record<id, ProfileRequestState>` + `_profileReqSeq` 自增 `requestId`，响应时仅当 `requestId` 为最新才写入，杜绝 A/B 切换陈旧响应污染；`clearProfileRequest(id)` 重置为 idle。
- ✅ 无障碍：skip-link、路由切换焦点管理（`main` `tabIndex={-1}` + `focus()`）、语义地标、`role="status"`/`role="alert"`/`aria-live`、`aria-current`/`aria-pressed`、44px 触控目标、WCAG AA 对比度。
- ✅ 响应式：传记页 `grid grid-cols-1 lg:grid-cols-3`，移动端单栏重排（正文 `order-1` 置顶 → 时间线 `order-2` → 史料 `order-3`），桌面三栏；全站无导致横向溢出的固定宽度 / `whitespace-nowrap` / `overflow-x`。
- ✅ Design Lab：`/design-lab` 临时路由 + `DesignLabPage`，集中展示色板/字体/组件/动效/素材降级/无障碍，不进正式导航，共用同一套 Token/CSS。
- ✅ PWA 收尾：缓存策略抽离为纯函数 `src/lib/swCachePolicy.ts`（`isNeverCachePath`/`isCacheableStaticPath`/`isAppNavigationPath` + 常量，被单测覆盖），`sw.js` 顶部注释指向该源码并要求内联等价实现同步；离线深链接回退 `index.html`、显式静态白名单不变；`public/assets/oriental/README.md` 说明东方素材接入、降级与合规（aria-hidden、不下载字体、不篡改文化、不提交真实存档）。
- ✅ ESLint 链路：`.eslintrc.cjs`（ESLint 8 经典配置，typescript-eslint + react + react-hooks + jsx-a11y），`package.json` 新增 `lint` / `lint:fix`；`npm run lint` 零错误零警告。
- ✅ 测试：原 32 项保留并适配新 store（`characterRepository.test.ts` 改为断言 `profileRequestStateById`），新增 34 项（视觉组件 15 / 媒体降级 7 / swCachePolicy 4 / design-lab 路由 3 / 竞态 3 / App 2），共 **66 项全绿**。
- ✅ 验证：`py_compile` 通过、pytest 19 项通过、`save-schema tsc` 通过、`web tsc --noEmit` 通过、`npm run lint` 零问题、`vitest run` 66 项通过、`vite build` 通过（433 模块）。
- ⚠️ 未做（留待后续 Phase）：真实 CK3 解析 / FastAPI 后端 / LLM 传记生成 / 家族树 / 地图 / 改数据契约 / 大规模换路由 / WebGL。

---

## Phase 1C.1 —— 验收修复与视觉收口（✅ 本轮已完成）

> 范围边界（硬性）：**不**开始 FastAPI / Rakaly / 真实 CK3 存档解析 / LLM 接入。仅做验收修复、视觉收口、素材审计与文档同步，并（经用户授权）推送到远端。

九节完成情况：

1. **人物加载竞态（按 ID 管理请求 + in-flight Map）**：`store.ts` 的 `profileRequestStateById` + 模块级 `profileInflightById` 已在前序落地；本轮补齐 `BiographyPage.test.tsx`（12 项）覆盖「初次按需加载 / 未知人物不取档 / A→B→A 复用 in-flight / 未知人物守卫」等，彻底消灭陈旧响应污染。
2. **Service Worker 离线导航**：重组 `sw.js` fetch（先拒非 GET / 跨源 / Authorization / 私有路径 → navigate 仅允许 `isAppNavigationPath` → 非 navigation 才进静态缓存）；抽离可测试 handler `src/lib/swHandler.ts` + `swHandler.test.ts`（13 项）。
3. **BiographyPage 测试补齐**：覆盖 11 + 1 项（初次加载 / 未知人物 / 点击时间线更新证据 / IntersectionObserver 更新章节与 aria-current / 滚动锁忽略 Observer / reduced-motion 不 smooth scroll / 桌面 smooth scroll / 移动端不滚动 / A→B→A 竞态 / 密度按钮 aria-pressed / 默认节点 aria-current / 卸载 disconnect）。
4. **路由无障碍完善**：`document.title` 随路由更新（传记页含人物名）；切换人物 A→B 时 title 更新、焦点经 `mainRef.focus({preventScroll:true})` 重入 `<main>`，依赖 `route.path` 而非仅 `route.name`；`router.getSnapshot` 防御性对齐 `window.location`，消除跨测试陈旧路由。
5. **克制但华丽的动效（reduced-motion 全部降级）**：解析页墨线延伸 + 朱砂落印；时间线当前章节连线点亮 + 脉冲；传记章节 `whileInView` 淡入 + `InkDivider` 墨线铺开；`EvidencePanel` 交叉淡入（`AnimatePresence mode="wait"` 生产语义保持）；`MotionConfig reducedMotion="user"` + CSS 媒体查询双重降级。
6. **东方素材整理**：为实际被构建引用的 3 张大图生成 WebP（Pillow）——`red-seal` 无损 **-53.7%**（922,554 B）、`paper-texture` 有损 q82 **-96.6%**（72,528 B）、`oriental-hero-bg` 有损 q82 **-95.2%**（112,134 B）；CSS 背景走 `image-set(...)` 优先 WebP、PNG 回退；4 张未使用/参考图（`ref_full_total` / `evidence-icons` / `oriental-dividers` / `oriental-ornament-pack`）移出 `public/` 至 `docs/design-reference/`（不进 `dist`、不进 `git`）。
7. **细节修正**：`ParsePage` 移除 `eslint-disable`、改用 `useCallback` 并修 `react-hooks/exhaustive-deps`（最终 `npm run lint` **零错误零警告**）；清理 `vt.log` / `dist` / `__pycache__` / `.pytest_cache` 等临时产物并确认 `.gitignore` 覆盖（`*.log`、`apps/web/vt.log`、`docs/design-reference/`）；`PageTransition` 经 `AnimatePresence mode="wait"` 统一使用。
8. **验证 + git 推送**：全套复跑（见文末「本轮（Phase 1C.1）验证结果」），**用户已授权 git 推送**至远端公开仓库。
9. **东方素材实际接入与审计**：建立 `docs/ASSET_AUDIT.md` 审计表（文件名 / 尺寸 / 是否引用 / 引用页面组件 / 仅 Design Lab / 参考图 / 裁切 / 透明化 / WebP / 最终决定）。约束落实：`red-seal` 至多两个正式场景（起始页 / 解析页，恰为上限）；`oriental-dividers` 评估提取 1–2 条（参考）；`paper-texture` 低透明度；`oriental-hero-bg` 仅起始页；`evidence-icons` / `ornament-pack` 评估为暂不使用（仅提取所需单件）；`ref_full_total` 已移出 `public`。

---

## Phase 2A —— 本地 CK3 存档库、解析器评估与 Mod 感知解析 MVP（✅ 本轮已完成）

> 范围边界（硬性）：用户不玩铁人，铁人支持非本轮验收目标，但必须支持用户实际存档所用的二进制 SAV0101 格式。不接入 LLM / 不生成传记正文 / 不实现地图和家族树。

完成项：
- ✅ 解析技术 Spike（实测定方案）：`tools/ck3-reader`（基于 `ck3save 0.4.3` + `jomini`，Rust sidecar，MIT）melt 真实二进制 SAV0101（1.19.0.6，62MB）；占位全量 token 表（65536 条）使仓库可独立构建，melt 完整、未知 token=0；结论见 `docs/parser-evaluation.md`。
- ✅ FastAPI 后端（`apps/server`）：`adapters/`（protocol 头检测 + Ck3ReaderAdapter subprocess 安全调用，超时/退出码/stderr 捕获、不 shell=True）、`services/`（LocalSaveDiscovery / ModResolver / CharacterExtractor / DirectoryWatcher / GameDataResolver / SaveRegistry / LocalizationLoader / SettingsStore）、`routers/saves.py`（health/settings/paths/local-saves 全套 + watch + inspect/mods/parse + characters/{cid} + DELETE）。
- ✅ 本地存档自动发现：默认 Windows Known Folder（不硬编码），支持普通/OneDrive/手动/自定义；扫描 `.ck3` 返回 stable id/fileName/size/modified/isAutosave/游戏版本/日期/状态/Mod 数/解析状态。
- ✅ 目录监听（可关闭）：新增/覆盖/autosave 更新/删除/重命名；写入中不得解析——`wait_until_stable()` 只读 stat 等稳定再复制副本，绝不长期占用原存档。
- ✅ Mod 感知：`ModCompatibilityReport`（required/found/missing/version_mismatch/corrupted/localization_available/playset_diff）；真实存档实测 33 Mod（全 ugc_），本机找到 33 / 缺失 0 / 损坏 0 / 版本不匹配 27；缺失/损坏/未知字段不阻断、不崩溃。
- ✅ 人物索引与按需 Profile：真实存档 35,078 人物；仅 melt 一次，按需生成单角色档案，不一次性生成全部；`EntityRef.resolved` 标记未解析字段，不伪造名称。
- ✅ 前端后端双模式：`LocalSavesPanel` + `api.ts` + `realRepository` + `store.backendMode`；后端不可用时整块不渲染、回退 Mock 演示。
- ✅ 数据契约同步：`EntityRef.resolved` 在 TS（`save-schema`）与 Python 同步；`save-schema` 契约测试 19 项通过。
- ✅ 测试（全绿）：后端 pytest **45**（单元 + 真实 62MB 集成，集成须 `SHIGUAN_TEST_SAVE` 环境变量，默认占位避免泄露本地路径）；前端 `tsc` 0 错 / `eslint` 0 错 0 警告 / `vite build` 437 模块 / Vitest **99**；save-schema 契约 19。
- ✅ 安全：真实存档经 `.gitignore`（`*.ck3`/`data/`）排除；源码硬编码本地路径已改为环境变量；汇报见 `docs/phase2a-report.md`。
- ⚠️ 限制（诚实披露）：enum 字段（信仰/王朝/头衔）中文化需真实 token 表（rakaly 从 Ck3.exe 导出，按 PDS 限制不随项目分发），当前以数字呈现不伪造；铁人未做；LLM/地图/家族树未做。

---

## Phase 2B —— 后续（真实 token 中文化 / 传记管线 / 地图家族树）

> Phase 2 的「后端 + 真实解析 MVP」已在 Phase 2A 完成（见上）。本节为 Phase 2B 及以后剩余项。

1. 初始化 `apps/server`（FastAPI + Pydantic + SQLite）—— **已在 Phase 2A 落地**。
2. 实现 `SaveParserAdapter` 协议与 `PlaintextAdapter`（自研 Python PDX 文本解析器，覆盖人物相关字段）—— 协议已落地；明文适配器分支待接。
3. 实现 `RakalyCliAdapter` 或真实 token 表接入（检测二进制/铁人，melt 后语义名中文化）—— Phase 2A 用 ck3save sidecar + 占位 token 表，真实 token 表替换可得中文信仰/王朝/头衔。
4. 文件检测（`inspect`）、解压、格式转换、人物索引、本地化加载 —— **已在 Phase 2A 落地**。
5. 标准人物档案：基本信息、家庭关系、当前/历史头衔、基础时间线 —— 基础字段已落地，扩展字段（性别/关系/头衔/死亡历史）为后续。
6. 解析测试（无效/空/压缩/纯文本/不支持二进制/缺解析器/非 UTF-8/超大/重复键）—— **已在 Phase 2A 落地**。
7. 后端与前端打通上传→解析→选择→传记的纵向链路 —— **基础链路已在 Phase 2A 落地（LocalSavesPanel → 后端 → 传记页）**。

---

## Phase 2 —— 存档解析 MVP（原总体计划，已被 Phase 2A / 2B 取代）

> 以下为早期总体计划，供对照；实际落地以 Phase 2A（已完成）与 Phase 2B（后续）为准。

1. 初始化 `apps/server`（FastAPI + Pydantic + SQLite）。
2. 实现 `SaveParserAdapter` 协议与 `PlaintextAdapter`（自研 Python PDX 文本解析器，覆盖人物相关字段）。
3. 实现 `RakalyCliAdapter`（检测二进制/铁人，调用外部 `rakaly` melt，缺失显式报错）。
4. 文件检测（`inspect`）、解压、格式转换、人物索引、本地化加载。
5. 标准人物档案：基本信息、家庭关系、当前/历史头衔、基础时间线。
6. 解析测试（无效/空/压缩/纯文本/不支持二进制/缺解析器/非 UTF-8/超大/重复键）。
7. 后端与前端打通上传→解析→选择→传记的纵向链路。

1. 初始化 `apps/server`（FastAPI + Pydantic + SQLite）。
2. 实现 `SaveParserAdapter` 协议与 `PlaintextAdapter`（自研 Python PDX 文本解析器，覆盖人物相关字段）。
3. 实现 `RakalyCliAdapter`（检测二进制/铁人，调用外部 `rakaly` melt，缺失显式报错）。
4. 文件检测（`inspect`）、解压、格式转换、人物索引、本地化加载。
5. 标准人物档案：基本信息、家庭关系、当前/历史头衔、基础时间线。
6. 解析测试（无效/空/压缩/纯文本/不支持二进制/缺解析器/非 UTF-8/超大/重复键）。
7. 后端与前端打通上传→解析→选择→传记的纵向链路。

---

## Phase 3 —— AI 传记生成

1. OpenAI 兼容接口层（支持 llama.cpp/LM Studio/Ollama/OpenAI，默认本地）。
2. 人物档案压缩（步骤 5）。
3. 提纲生成（步骤 6）→ 正文生成（步骤 7）。
4. 事实校验（步骤 8）与自动修正重试。
5. 生成历史、编辑与保存、文风切换。
6. 传记测试（时间倒置/推断当事实/虚构配偶头衔/无证据对白/每章关联事件/非法 JSON 重试）。

---

## Phase 4 —— 增强沉浸感

1. 家族树、世代切换、家族兴衰时间线。
2. 地点经历可视化。
3. 多人物合传、王朝总传。
4. Markdown / HTML 导出。
5. PWA 完善（manifest、离线壳、静态缓存、不缓存敏感数据）。

---

## 当前风险与遗留问题

1. **铁人存档本地解码依赖用户自备令牌表**：无令牌且不愿用远程时，ironman 无法本地解析。需在 UI 明确引导。
2. **自研 PDX 文本解析器的健壮性**：需覆盖补丁间语法漂移与超大文件；Phase 2 起用真实存档样本持续校准。
3. **jomini JS/WASM 备选未验证**：若 Python 文本解析在大存档上性能不足，后续可评估前端/Node 直解。
4. **Rakaly 仅作真实 token 表导出来源**：主解析库 `ck3save`/`jomini` 均为 **MIT**（已核实，从 Cargo 源码构建，不复制源码、不下载预编译 exe）；rakaly 仅用于导出真实 token 表（按 PDS 限制不随项目分发），合规风险已排除。
5. **~~未做 TS 类型检查 / eslint / vite build~~**：TS 严格类型检查已在 Phase 0.5 建立；`vite build` 早在 Phase 1A 通过；ESLint 8 链路已于 Phase 1C 建立（`npm run lint` / `lint:fix`）。前端静态检查链（tsc + eslint + vite build）现已完整。

---

## 本轮（Phase 0.5）验证结果

- Python 语法检查：`py_compile packages/save-schema/py/models.py` → 通过。
- Python 契约测试：`pytest packages/save-schema/py/tests/` → **19 项全部通过**（非法枚举拒绝、空 eventIds 拒绝、Profile/ParsedSave 序列化往返、SaveInspection/ParsedSave 生成、Mock 包裹与 CharacterProfile 分离、JSON fixture 读取）。
- TypeScript 严格类型检查：`tsc --strict --noEmit -p packages/save-schema/tsconfig.json` → 通过（无类型错误）。
- 文档与配置文件：均已同步更新并通过链接一致性核对。
- 就绪判定：**已具备进入 Phase 1A 的条件**（契约双语言同步、运行时校验到位、Mock 包裹机制可用、索引/档案分离就绪）。

---

## 本轮（Phase 1B）验证结果

- Python 语法检查：`py_compile packages/save-schema/py/**/*.py` → 通过。
- Python 契约测试：`pytest packages/save-schema/py/tests/` → **19 项全部通过**（同 Phase 0.5 覆盖项：非法枚举拒绝、空 eventIds 拒绝、Profile/ParsedSave 序列化往返、SaveInspection/ParsedSave 生成、Mock 包裹与 CharacterProfile 分离、JSON fixture 读取）。
- TypeScript 严格类型检查（契约）：`tsc --strict --noEmit -p packages/save-schema/tsconfig.json` → 通过（无类型错误）。
- Web 严格类型检查：`tsc --noEmit`（apps/web，strict）→ 通过（无类型错误）。
- 前端测试：Vitest + RTL + jsdom → **32 项全部通过**（mockParse 4 / buildOutline 3 / router 3 / contractValidate 6 / characterRepository 5 / SelectPage 7 / EvidencePanel 4）。
- 生产构建：`vite build` → 通过（421 模块转换、产物渲染正常；沙箱内 `emptyOutDir` 的回收站拦截属环境问题，非代码缺陷，已用临时输出目录验证成功）。
- 文档与配置：README / architecture / roadmap / AGENTS / fixtures/mock/README 已同步至 Phase 1B 完成态；`.gitignore` 已移除 `apps/web/public/sw.js`、保留 `apps/web/dist/`。
- Git 卫生：`node_modules/` `dist/` `__pycache__/` `.pytest_cache/` `.vite/` 真实存档（`*.ck3`） `.env` 均被忽略；工作树无真实存档或密钥。
- 就绪判定：**已具备进入 Phase 1C 的条件**（纵向 Mock 链路打通、路由/状态恢复可靠、时间线双向同步、档案按需加载、PWA 安全缓存、测试基线 32 项）。

---

## 本轮（Phase 1C）验证结果

- Python 语法检查：`py_compile packages/save-schema/py/**/*.py` → 通过。
- Python 契约测试：`pytest packages/save-schema/py/tests/` → **19 项全部通过**（同 Phase 1B 覆盖项：非法枚举拒绝、空 eventIds 拒绝、Profile/ParsedSave 序列化往返、SaveInspection/ParsedSave 生成、Mock 包裹与 CharacterProfile 分离、JSON fixture 读取）。
- TypeScript 严格类型检查（契约）：`tsc --strict --noEmit -p packages/save-schema/tsconfig.json` → 通过（无类型错误）。
- Web 严格类型检查：`tsc --noEmit`（apps/web，strict）→ 通过（无类型错误）。
- 前端静态检查（ESLint）：`npm run lint`（ESLint 8 + typescript-eslint + react + react-hooks + jsx-a11y）→ **零错误零警告**（修复 InkDivider 冗余 role、未用 import、JSX 未转义引号等 6 项问题）。
- 前端测试：Vitest + RTL + jsdom → **66 项全部通过**（原 32 项保留并适配新 store + 新增 34 项：visualComponents 15 / mediaComponents 7 / swCachePolicy 4 / router.designlab 3 / store.race 3 / App 2）。
- 生产构建：`vite build` → 通过（433 模块转换、产物渲染正常；沙箱内 `emptyOutDir` 回收站拦截属环境问题，非代码缺陷，已用临时输出目录验证成功）。
- 文档与配置：README / AGENTS / architecture / roadmap / fixtures/mock/README 已同步至 Phase 1C 完成态；`apps/web/package.json` description 更新；`.gitignore` 维持 `apps/web/dist/`、`public/sw.js` 纳入版本库。
- Git 卫生：`node_modules/` `dist/` `__pycache__/` `.pytest_cache/` `.vite/` 真实存档（`*.ck3`） `.env` 均被忽略；工作树无真实存档或密钥。
- 就绪判定：**已具备进入 Phase 2 的条件**（东方数字史馆视觉定稿、响应式单栏重排、键盘可达性/ARIA/reduced-motion、加载竞态修复、PWA 缓存策略纯函数化、ESLint 链路闭环、测试 66 项基线）。

---

## 本轮（Phase 1C.1）验证结果

- Python 语法检查：`py_compile packages/save-schema/py/**/*.py` → 通过。
- Python 契约测试：`pytest packages/save-schema/py/tests/` → **19 项全部通过**（同前序覆盖项：非法枚举拒绝、空 eventIds 拒绝、Profile/ParsedSave 序列化往返、SaveInspection/ParsedSave 生成、Mock 包裹与 CharacterProfile 分离、JSON fixture 读取）。
- TypeScript 严格类型检查（契约）：`tsc --strict --noEmit -p packages/save-schema/tsconfig.json` → 通过（无类型错误）。
- Web 严格类型检查：`tsc --noEmit`（apps/web，strict）→ 通过（无类型错误）。
- 前端静态检查（ESLint）：`npm run lint`（ESLint 8 + typescript-eslint + react + react-hooks + jsx-a11y）→ **零错误零警告**（本轮修复 `ParsePage` `useCallback` 的 `exhaustive-deps` 冗余/缺失依赖，最终干净）。
- 前端测试：Vitest + RTL + jsdom → **96 项全部通过**（15 个测试文件；含新增 `BiographyPage.test.tsx` 12 项、`swHandler.test.ts` 13 项，原 66 基线保留并适配）。
- 生产构建：`vite build --outDir /tmp/shiguan-build` → 通过（**434 模块**转换、产物渲染正常；沙箱内 `emptyOutDir` 回收站拦截属环境问题，非代码缺陷，已用临时输出目录验证成功）。
- 东方素材体积：PNG 合计约 6.49 MB → WebP 合计约 1.11 MB；`red-seal` 无损 -53.7%，`paper-texture` 有损 -96.6%，`oriental-hero-bg` 有损 -95.2%；CSS 走 `image-set` 优先 WebP、PNG 回退。
- 文档与配置：新增 `docs/ASSET_AUDIT.md`（素材审计表）；`roadmap.md` 增加 Phase 1C.1 节与本验证块；`.gitignore` 新增 `*.log` / `apps/web/vt.log` / `docs/design-reference/`；`index.css` 背景图改为 `image-set`；`DesignLabPage` 移除 `__not_exist__.png` 死引用（不再产生 404）。
- Git 卫生：`node_modules/` `dist/` `__pycache__/` `.pytest_cache/` `.vite/` `vt.log` `docs/design-reference/`（大图参考，约 9 MB）真实存档（`*.ck3`） `.env` 均被忽略；工作树无真实存档或密钥；提交集已 `git add -A` 刷新（含 3 张 `.webp` 与移除的 4 张参考图）。
- 推送：经用户明确授权，推送至公开远端仓库（默认分支 `master`）。
- 就绪判定：**Phase 1C.1 验收修复与视觉收口完成**，前端静态检查链（tsc + eslint + vite build）与 96 项测试基线全部绿；仍严格未触碰 FastAPI / Rakaly / 真实 CK3 解析 / LLM。
