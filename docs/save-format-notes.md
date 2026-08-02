# 史官 SHIGUAN —— CK3 存档格式与解析笔记

本文档记录《十字军之王 III》存档的格式特征、识别方法、各类型处理方式，以及解析路线的许可证与维护状态。它是 `save-schema` 与解析适配器实现的参考。

> 重要：CK3 文件格式随游戏版本补丁变化，本笔记描述的是稳定骨架；具体字段需结合真实存档与游戏本地化持续校准。

---

## 1. 存档的四种编码形态

根据 `ck3save` 源码的 `Encoding` 枚举，CK3 存档有四种编码：

| 编码 | 结构 | 内容 | 是否压缩 |
|---|---|---|---|
| `Text` | save id 行 + 未压缩文本 gamestate | 明文 Clausewitz | 否 |
| `TextZip` | save id 行 + 明文头 + 压缩明文 gamestate 的 zip | 明文 | 是（zip） |
| `BinaryZip` | save id 行 + 二进制头 + 压缩二进制 gamestate 的 zip | 二进制 | 是（zip） |
| `Binary` | save id 行 + 未压缩二进制 gamestate | 二进制 | 否 |

此外按用途区分：
- **标准存档（standard）**：`TextZip` 或 `BinaryZip`，头与 gamestate 在 zip 内。
- **自动存档（autosave）**：未压缩的 `Text` 或 `Binary` gamestate（无外层 zip）。
- **铁人存档（ironman）**：本质上是带 PDS 二进制格式的标准/二进制存档，但 gamestate 用令牌(token)编码，**解码需要 TokenResolver**。

### 识别策略（对应 `SaveInspection`）

1. 探测文件尾部是否存在 ZIP 的 EOCD 签名（`50 4B 05 06`）。
   - 命中 → 这是一个 zip 容器。
     - 读取 zip 内 gamestate 的头部字节：若第 3、4 字节为 `01 00` → `ironman`；
     - 否则根据头是否为二进制特征判断 `binary_zip` 或 `text_zip`。
   - 未命中 → 这是自动存档的未压缩 gamestate：
     - 尝试 UTF-8 解码并匹配 Clausewitz 结构（`CK3txt` / 对象 `{}` / `=` 赋值）→ `text`；
     - 解码失败或呈二进制特征 → `binary`。
2. 编码判定：CK3 引号字符串用 **UTF-8**（EU4 用 Windows-1252）。纯文本 CK3 应优先 UTF-8 解码；遇到非 UTF-8 内容应按 `windows-1252` 或标记 `unknown` 并报错，绝不强行按 UTF-8 吞掉导致乱码。

> 注意：zip 在文件**尾部**定位，所以可以先"假定是 zip"再回退，避免扫描上百 MB 才放弃。但实现时必须显式回退，不能猜错后继续把二进制当文本解析。

---

## 2. 各类型处理方式（处理矩阵）

| 输入类型 | 本地可解析？ | 处理流程 |
|---|---|---|
| **纯文本 / 解压后的 gamestate** | ✅ 是 | 直接走自研 Python PDX 文本解析器（路线 A）。 |
| **标准 .ck3（TextZip）** | ✅ 是 | `zipfile` 解压取出 gamestate → 路线 A 解析明文。 |
| **二进制 .ck3（BinaryZip / Binary）** | ⚠️ 需 Rakaly CLI | 调用 `rakaly` 将其 melt/转换为明文 → 路线 A。缺失 CLI 时显式报错。 |
| **铁人存档（ironman）** | ⚠️ 需 Rakaly CLI + 用户令牌表 | 用户提供 `RAKALY_IRONMAN_TOKENS_PATH`，由 `rakaly` 用令牌解码 → 明文 → 路线 A。无令牌且未开启远程时直接报错。 |
| **非 CK3 / 损坏文件** | ❌ 否 | `inspect()` 判定为不支持 → 解析阶段报错："失败阶段：文件检测；建议：请确认这是有效的 CK3 存档"。 |

**铁律（来自规范第十二、九条）**：
- 二进制需要外部组件时：①检查是否存在；②不存在给清楚安装提示；③**不得静默失败**；④**不得把二进制当普通文本强行解析**；⑤**不得伪造已解析成功的结果**。

---

## 3. 解析路线调研与对比

### 路线 A：自研 Python PDX（Clausewitz）文本解析器 —— **主链路（明文侧）**

- **做什么**：解析 CK3 明文（调试格式）的 Clausewitz 语法：`key = value`、`key = { ... }`、无引号键、数组、日期 `YYYY.MM.DD`、布尔 `yes/no`、隐藏对象等。
- **为什么可行**：规范只禁止"从零写无法维护的**二进制**解析器"。明文格式稳定、文档较多、且是铁人 melt 后的最终形态，是可控可维护的子集。
- **范围克制**：Phase 2 只需覆盖人物档案相关字段（character、dynasty、house、title、culture、faith、war、memory、relation 等），不必一次性支持全部语法。先做健壮的"对象/数组/标量"递归解析器，再按需读取子路径。
- **风险**：补丁间语法漂移、超大文件（数百 MB）内存压力、重复键与值列表歧义。对策：流式/分块读取、显式 duplicate 处理策略、对超大文件给出大小阈值提示。

### 路线 B：Rakaly CLI（外部二进制）—— **二进制/铁人侧**

- **是什么**：Rakaly 提供的命令行工具，能把二进制/铁人 CK3 存档"融化(melt)"为标准明文。核心解析能力来自 Rust 库 `jomini`（底层，MIT，~1GB/s）与 `ck3save`（CK3 高层封装，MIT）。
- **许可**：Rakaly / jomini / ck3save 均为 MIT（部署前须再次核实 CLI 具体许可与分发条款）。**绝不**把它们的源码大量复制进本项目（规范第十条）。
- **铁人令牌限制**：ironman 解码依赖 TokenResolver，令牌表按 PDS 协议**不得随库分发**，也不得公开推导方法。因此本地铁人解码必须由用户自备令牌文件；否则只能建议用户用 Rakaly 在线转换器（离开本地，需明确隐私警告），或放弃。
- **失败处理**：`rakaly` 不存在 → 报错并给安装提示（如 `cargo install rakaly` 或下载发布二进制）。命令执行失败 → 捕获 stderr 并展示，不伪造。

### 备选（记录，暂不纳入）

- **jomini JS/WASM（`npm i jomini`）**：可在浏览器/Node 解析明文与二进制，零依赖、<100KB gzip。若要"前端直接解析"或"Node 后端"，这是强选项。但会引入第二运行时，与当前 Python 后端定位冲突，留作后续评估。
- **ck3-savetools（Python，BSD-2）**：纯 Python，但**不支持 ironman**、较慢（约 1 分钟/存档），定位是"开发基础库"。可作为路线 A 的参考实现，但自行维护更贴合需求。
- **scorpdx/ck3json + 导出器**：依赖第三方 Windows exe，**违反"不下载来源不明可执行文件"硬约束，不采用**。

---

## 4. 本地化（localization）

CK3 的游戏内名称（头衔、特质、文化、信仰、事件等）多为本地化 key，需结合游戏目录下的本地化文件（`game/localization/.../*.yml`）解析为可读中文/英文。解析器应接受"游戏目录"作为可选输入，构建 `localization: key -> name` 表。缺失本地化时回退到 key 本身，并在证据告警中标注"名称未经本地化"。

---

## 5. 已知坑位（实现时需警惕）

1. **隐藏对象（hidden objects）**：如 `levels={ 10 0=2 1=2 }` 是数组里夹对象，解析时需按 `levels = [10, {0=2, 1=2}]` 处理。
2. **二进制有理数值（binary rational）**：CK3 二进制对分数（如年龄）的编码与明文不同，直接按明文解码会算出"几万岁"。二进制一律先经 Rakaly melt，**不自行解码**。
3. **日期编码**：明文为 `YYYY.MM.DD` 字符串；二进制为整数（游戏内天数）。统一在时间线层转换为可读日期，并保留原始值以便溯源。
4. **补丁漂移**：不同 1.x 版本字段名/结构可能变化；索引器对未知字段采取"忽略 + 记录"，不崩溃。
5. **编码**：CK3=UTF-8；误用 Windows-1252 会破坏非西欧字符（如北欧、西里尔、中文 mod 名称）。

---

## 6. 解析阶段状态机（对应"存档解析页"）

```
detect → unzip → convert(melt, 仅二进制/铁人) → read_characters
       → build_index → load_localization → done
```

任一阶段失败都必须暴露：失败阶段 / 可读错误 / 建议操作 / 技术详情折叠栏。进度必须来自真实任务状态，禁止虚假定时进度条。
