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
- 核心类型：`CharacterProfile`（原始数据层）、`TimelineEvent`（带 `confidence`）、`EvidenceWarning`、`Biography`（展示层，只引用事件 ID）。
- `confidence`：`confirmed` / `inferred` / `uncertain`。推断不得写成确定事实。

## 5. 传记管线（详见 docs/biography-pipeline.md）

八步：解析 → 索引 → 标准档案 → 时间线 → 压缩 → 提纲 → 正文 → 事实校验。
- 两次模型调用：先提纲（每章 `eventIds` 非空且来自时间线），再正文（每章追溯事件 ID）。
- 事实校验自动进行，发现问题要求模型修正，不展示错误内容。
- 禁止虚构对白 / 内心活动 / 战役细节 / 篡改时间关系。

## 6. 目录约定

- 不为符合目录而制造空包。`apps/*`、`packages/shared`、`packages/biography-engine`、`scripts` 在对应 Phase 才建立。
- 真实存档 / 数据库 / 上传目录（`data/`、`*.ck3` 等）已被 `.gitignore` 忽略，不提交。
- `.env` 被忽略；`.env.example` 不含真实密钥。

## 7. 当前状态（Phase 0 完成）

已建立：数据契约、四份 docs、`.env.example`、`.gitignore`、README、AGENTS、fixtures/mock 契约。
未建立：前端/后端骨架（Phase 1/2）、TS 编译环境（Phase 1 补齐）。
下一轮见 `docs/roadmap.md` 的 Phase 1。

## 8. 沟通风格

面向用户的汇报用简体中文，结论先行、给出可验证证据（命令输出/文件路径/测试结果），
并明确列出"当前限制"与"下一轮建议"。不要只给建议——能安全完成的工作直接在项目内完成。
