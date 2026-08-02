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

## Phase 1 —— 可交互前端原型（下一轮建议）

**目标**：用可信 Mock 数据实现核心页面与交互，验证 UX 与视觉语言。

范围：
1. 初始化 `apps/web`（Vite + React + TS + Tailwind + Zustand + Framer Motion + PWA 骨架）。
2. 在 `fixtures/mock/` 落地 1–2 份**明确标注为非真实解析**的 `CharacterProfile` + `TimelineEvent` 样例（含 confirmed/inferred/uncertain 三种证据）。
3. 实现页面：
   - 起始页（深酒红/骨白/暗金/炭黑克制配色，拖拽上传区，最近项目，隐私说明）。
   - 存档解析过程页（阶段状态来自 Mock 任务状态，非假进度条）。
   - 人物选择页（搜索/筛选/卡片摘要）。
   - 人物传记页（桌面三栏 + 移动端单栏，章节式正文，可缩放时间线，史料依据面板，不确定提示，滚动同步高亮）。
4. 移动端适配与键盘可达性、无障碍对比度、`prefers-reduced-motion`。
5. 前端测试（上传/错误反馈/搜索/时间线交互/移动端/键盘/长文性能）。

验收：能离线用 Mock 数据完整走通"选人 → 看传记 → 看时间线 → 看证据"。

---

## Phase 2 —— 存档解析 MVP

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
4. **Rakaly CLI 具体许可证与分发条款**：部署前须再次核实，避免合规风险。
5. **未做 TS 类型检查环境**：Phase 1 初始化前端时需建立 `tsconfig` + `tsc --noEmit` + eslint + `vite build` 检查链。

---

## 本轮（Phase 0）验证结果

- Python 语法检查：`C:\Users\Rosemary\.workbuddy\binaries\python\versions\3.13.12\python.exe -m py_compile packages/save-schema/py/models.py` → 通过（无语法错误）。
- TypeScript：尚未建立编译环境（Phase 1 补齐），`types.ts` 按 TS 严格风格手写，字段与 Python 模型逐一对齐。
- 文档与配置文件：均已写入并通过人工核对链接一致性。
