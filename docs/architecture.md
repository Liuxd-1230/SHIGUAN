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
│  ├─ web/            # React + Vite 前端（Phase 1 建立）
│  └─ server/         # FastAPI 后端（Phase 2 建立）
├─ packages/
│  ├─ shared/         # 前后端共享工具（Phase 1+）
│  ├─ biography-engine/  # 传记生成与校验（Phase 3）
│  └─ save-schema/    # ✅ 已完成：数据契约
│     ├─ src/types.ts # TS 类型（事实来源）
│     └─ py/models.py # Pydantic 镜像
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

## 8. 当前进度（Phase 0 已完成）

- ✅ 目录结构（最小、非空）
- ✅ 数据契约：`packages/save-schema/src/types.ts` + `py/models.py`
- ✅ 四份文档：`architecture.md` / `save-format-notes.md` / `biography-pipeline.md` / `roadmap.md`
- ✅ `.env.example`（无真实密钥）、`.gitignore`、`README.md`、`AGENTS.md`
- ✅ `fixtures/mock/README.md`（定义 Phase 1 的 Mock 数据契约）
- ❌ 未实现任何解析器（按规范，Phase 0 不写虚假完整解析器）
- ❌ 未搭建前端/后端骨架（留给 Phase 1/2）

下一轮（Phase 1）建议见 `roadmap.md`。
