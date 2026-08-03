# CK3 人物字段研究（Phase 2B / M1）

> 目的：为"史官 SHIGUAN"的人物档案与人生时间线提供**可追溯、不猜测**的字段依据。
> 本文所有数字均来自对一份真实二进制存档的实测，任何未经验证的推测都显式标注为「推断」或「未验证」。

## 0. 结论摘要（先看这个）

本轮推翻了 Phase 2A 遗留的三条**错误假设**，它们是此前人物关系提取命中率为 0 的根因：

| 旧假设（错误） | 实测事实 | 影响 |
| --- | --- | --- |
| `t315f` = `father` | `t315f` 实为 **`council_task`**（议会任务） | 提取出的"父亲"全是脏数据 |
| `t280a` = `mother` | `t280a` 实为 **`employer`**（雇主/所属宫廷） | 提取出的"母亲"全是脏数据 |
| `t2c68` = `death` | `t2c68` 实为 **`arrival_date`**（抵达日期） | 死亡日期恒为空，存活判定失效 |
| `t3b12` = `culture` | `t3b12` 实为 **`ethnicity`**（外貌族群），真正的 `culture` 是 `t27f4` | 文化字段取错 |

并确立一条对整个 Phase 2B 影响最大的结构性事实：

> **CK3 存档的人物块里根本不存在 `father` / `mother` 字段。**
> 亲子关系只在**父母一侧**以 `child` 列表存储，子女侧没有反向指针。
> 因此"某人的父母是谁"必须由 `child` 列表**反向建索引**得出，属于**推断（inferred）**，
> 不得当作存档直述的事实呈现。唯一的例外是 `real_father`（私生子的生父），
> 那是存档直述的 **confirmed** 事实，本存档中仅 48 例。

---

## 1. 研究方法（可复现）

### 1.1 为什么需要真实令牌表

CK3 的二进制存档（`SAV0101`）把所有字段名压缩成 16 位 **token id**。melt（解压转明文）时，
若没有 id→名称 的映射表，字段名就只能显示成占位符 `tXXXX`，语义无从判断。

此前项目用的是**占位表**（`tokens/ck3_tokens.txt`，65536 条 `id → tXXXX`）：
它能保证任何存档都被**完整** melt（`unknown_token_count = 0`，不丢数据），
但字段名不可读，只能靠人工猜语义——上表四条错误假设就是这么来的。

### 1.2 真实令牌表的获取方式

真实映射表内嵌在游戏主程序 `ck3.exe`（PE32+）的 `.rdata` 段里，是一个连续的 16 字节条目数组：

```c
struct Entry {          // 小端，16 字节
    uint64_t token_id;  // 偏移 0：token 数值 id
    const char *name;   // 偏移 8：指向 C 字符串的虚拟地址
};
```

本项目新增工具 `tools/ck3-reader/extract_tokens.py` 完成提取：

1. 解析 PE 头，建立 虚拟地址(VA) ↔ 文件偏移 的换算；
2. 用三元锚点 `living` / `dead_prunable` / `dead_unprunable` 定位表体
   （这三个 token 的 id 在游戏内**连续**：`0x2ce6 / 0x2ce7 / 0x2ce8`，可用于自校验）；
3. 从锚点向前后**双向扩展**，容忍数组中的空洞，直到条目不再合法；
4. 未提取到的 id 用 `tXXXX` 占位补齐，保证任何存档都不会因缺表而丢数据。

用法：

```bash
cd tools/ck3-reader
python extract_tokens.py --verify        # 读 CK3_EXE 或 SHIGUAN_CK3_GAME_DIR
```

**分发限制**：真实令牌表属于 Paradox 的游戏资产，**禁止随仓库分发**。
产物 `tokens/ck3_tokens_real.txt` 已被 `.gitignore` 排除（规则 `tools/ck3-reader/tokens/*_real.txt`）。
用户必须从自己安装的游戏里提取。`build.sh` 优先用真实表，缺失时自动回退占位表并提示。

### 1.3 提取结果与覆盖率

| 指标 | 数值 |
| --- | --- |
| 提取到的真实 token 数 | **8161** |
| 冲突（同 id 映射到不同名） | **0** |
| 存档中实际出现的 token 种类 | 1035 |
| 其中被真实表覆盖 | **1035 / 1035 = 100%** |
| 存档中 token 引用总次数 | 4,153,122，全部可解析 |

> 说明：早期一版"全 `.rdata` 无差别扫描"的实现产生了 1454 处冲突（大量假阳性），
> 已废弃；最终采用的是**连续块 + 锚点校验**版本，0 冲突。

### 1.4 交叉验证方式

为避免"Rust 实现和它自己的假设自洽"这种自证陷阱，本轮用**两套独立实现**互校：

- `tools/ck3-reader`（Rust，生产实现）
- `data/debug/expect.py`（Python，一次性核对脚本，仅本地，不进仓库）

两者按相同的层级规则、各自独立地扫描同一份 melt 明文，比对每个字段的命中计数。
下文表格中的计数即为两者一致的结果。

### 1.5 实测样本

| 项 | 值 |
| --- | --- |
| 存档 | 本机自动存档（62 MB，二进制 `SAV0101`） |
| 游戏版本（存档自报） | **1.19.0.6** |
| melt 后明文 | 约 87 MB |
| 存档内游戏日期 | `762.1.5`（开局后第 4 天） |
| 启用 Mod | 33 个（全部为创意工坊 `ugc_` 条目） |

> ⚠️ 该存档是**开局第 4 天**的自定义开局（Mod 提供的东亚剧本）。
> 这意味着"人生经历"类数据（统治史、战争、囚禁、记忆）在本存档中天然稀疏，
> 计数低**不代表提取失败**。判断提取是否正确必须看结构命中，不能只看比例。

---

## 2. 人物容器结构

人物**不在**单一容器里，而是分散在三处，且其中一处是嵌套的：

```
living={ ... }                  # 顶层，存活人物
dead_unprunable={ ... }         # 顶层，需要长期保留的死者（有历史意义）
characters={                    # 顶层容器 t06e3
    dead_prunable={ ... }       # 嵌套一层！可被游戏剪枝的死者
}
```

| 容器 | token | 存活 | 本存档条目数 |
| --- | --- | --- | --- |
| `living` | `t2ce6` | 是 | 35078 |
| `dead_unprunable` | `t2ce8` | 否 | 4781 |
| `dead_prunable` | `t2ce7`（嵌在 `characters` = `t06e3` 内） | 否 | 4237 |
| **合计** | | | **44096** |

校验：明文中 `first_name` 出现 44096 次，与三容器条目数之和**完全相等**，说明无遗漏。

> **实现要点**：因为 `dead_prunable` 比另外两个深一层，容器探测**不能**假设深度为 0，
> 必须在任意深度上匹配容器键。Phase 2A 的实现只扫 `living`，
> 直接漏掉了 9018 名死者（20.5%），而死者恰恰是"历史人物传记"的主体。

### 2.1 人物块层级

```
living={                      # 深度 D
    6433={                    # 深度 D+1：数字 id 条目
        first_name="..."      # 深度 D+2：直接标量字段
        traits={ 66 74 ... }  # 深度 D+2：列表容器
        family_data={         # 深度 D+2：子块
            child={ 7667 ...} # 深度 D+3
        }
        dead_data={           # 深度 D+2：存在即代表已死
            date=31.8.26      # 深度 D+3：真正的死亡日期
        }
    }
}
```

---

## 3. 字段清单

计数口径：分母 = 44096（全部人物）。「置信度」定义见 §3.4。

### 3.1 直接标量字段（人物块 深度 D+2）

| 字段 | token | 类型 | 命中 | 占比 | 置信度 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| `first_name` | `t2755` | string | 44096 | 100.0% | confirmed | 名，非全名；本存档 Mod 生成了 `Shunxian_9806_5148` 这类带后缀的键名 |
| `birth` | `t27e9` | date | 44096 | 100.0% | confirmed | 出生日期，格式 `年.月.日` |
| `nickname_text` | `t3884` | string | 44096 | 100.0% | confirmed | 绝大多数为空串，非称号 |
| `ethnicity` | `t3b12` | string | 44096 | 100.0% | confirmed | **外貌族群**（如 `asian_han_chinese`），**不是** culture |
| `skill` | `t29a5` | int[6] | 44096 | 100.0% | confirmed | 六维技能，顺序未在本轮验证 → 标记为未验证 |
| `traits` | `t0648` | int[] | 42916 | 97.3% | confirmed（键）/ unresolved（值） | 值是**数字 id**，需特质索引才能转名，见 §5 |
| `alive_data` | `t2751` | block | 35077 | 79.5% | confirmed | 仅活人有；注意比 `living` 少 1 |
| `weight` | `t0251` | block | 32176 | 73.0% | confirmed | 体重相关 |
| `court_data` | `t2752` | block | 31811 | 72.1% | confirmed | 宫廷归属 |
| `faith` | `t2f2b` | int id | 34725 | 78.7% | confirmed（键）/ unresolved（值） | 数字 id，如 `23` |
| `culture` | `t27f4` | int id | 34212 | 77.6% | confirmed（键）/ unresolved（值） | 数字 id，如 `87` |
| `family_data` | `t274f` | block | 17401 | 39.5% | confirmed | 见 §3.2 |
| `dynasty_house` | `t2e5e` | int id | 16089 | 36.5% | confirmed（键）/ unresolved（值） | 是**家族分支(house)**，不是 `dynasty`(`t280e`) |
| `female` | `t0625` | flag `yes` | 13554 | 30.7% | confirmed | 只写 `female=yes`；**缺省即男性** |
| `sexuality` | `t3334` | int | 7942 | 18.0% | confirmed（键）/ unresolved（值） | |
| `landed_data` | `t2753` | block | 5229 | 11.9% | confirmed | **存在即为封地持有者（统治者）** |
| `dead_data` | `t2750` | block | 9019 | 20.5% | confirmed | 见 §3.3；命中数 = 三容器死者总数 |
| `playable_data` | `t2754` | block | 3292 | 7.5% | confirmed | |
| `nickname` | `t2f68` | string key | 295 | 0.7% | confirmed | 真正的称号键（如 `nick_the_great`），需本地化 |
| `regnal_name` | `t336d` | string | 165 | 0.4% | confirmed | 王号 |
| `dna` | `t2acf` | base64 | 801 | 1.8% | confirmed | 外貌数据，本项目不使用 |
| `recessive_traits` | `t3422` | int[] | 634 | 1.4% | confirmed | |
| `inactive_traits` | `t3085` | int[] | 54 | 0.1% | confirmed | |
| `secret_faith` | `t3701` | int id | 12 | 0.0% | confirmed | |

### 3.2 `family_data`（`t274f`）子块

| 字段 | token | 类型 | 命中 | 占比 | 置信度 |
| --- | --- | --- | --- | --- | --- |
| `child` | `t2811` | id 或 id 列表 | 9299 人 / 17286 条边 | 21.1% | confirmed |
| `spouse` | `t2810` | id 或 id 列表 | 7398 人 / 7608 条边 | 16.8% | confirmed |
| `primary_spouse` | `t332f` | id | 7010 | 15.9% | confirmed |
| `former_spouses` | `t3241` | id 列表 | 791 | 1.8% | confirmed |
| `betrothed` | `t2bb9` | id | 412 | 0.9% | confirmed |
| `concubine` | `t2bd3` | id | 63 | 0.1% | confirmed |
| `concubinist` | `t336e` | id | 63 | 0.1% | confirmed |
| **`real_father`** | `t2a5b` | id | **48** | 0.1% | **confirmed** |
| `former_concubinists` | `t33a2` | id 列表 | 11 | 0.0% | confirmed |
| `former_concubines` | `t33a3` | id 列表 | 2 | 0.0% | confirmed |

> `child` / `spouse` 有**两种写法**：标量 `child=7667` 和列表 `child={ 7667 7862 }`。
> 解析器两种都要支持，否则会漏掉大量关系边。

### 3.3 `dead_data`（`t2750`）子块

| 字段 | token | 类型 | 命中 | 占比 | 置信度 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| `date` | `t06b5` | date | 9019 | 20.5% | confirmed | **真正的死亡日期** |
| `domain` | `t27e6` | id 列表 | 1790 | 4.1% | confirmed | 死时领地 |
| `reason` | `t2b64` | string key | 4188 | 9.5% | confirmed | 如 `death_disappearance`，需本地化 |
| `flavor` | `t2fcf` | string key | 376 | 0.9% | confirmed | |
| `liege` | `t292d` | id | 329 | 0.7% | confirmed | |
| `liege_title` | `t345a` | id | 329 | 0.7% | confirmed | |
| `life_expectancy` | `t335d` | float | 171 | 0.4% | confirmed | |
| `killer` | `t2766` | id | 348 | 0.8% | confirmed | **凶手**，时间线高价值 |
| `government` | `t2ef7` | string key | 102 | 0.2% | confirmed | |
| `named_title` | `t2dd0` | id | 79 | 0.2% | confirmed | |

### 3.4 `alive_data`（`t2751`）子块（M4/M5 将深化）

| 字段 | token | 命中 | 占比 | 置信度 |
| --- | --- | --- | --- | --- |
| `fertility` `t2846` / `health` `t2a5c` / `languages` `t0343` / `activity_data` `t381c` / `location` `t27f6` | — | 35077 | 79.5% | confirmed |
| `merit` `t3d30` | | 34931 | 79.2% | confirmed |
| `piety` `t2b27` | | 34100 | 77.3% | confirmed |
| `prestige` `t2b26` | | 30478 | 69.1% | confirmed |
| `influence` `t29f5` | | 29964 | 68.0% | confirmed |
| `variables` `t0555` | | 23395 | 53.1% | confirmed |
| `gold` `t2875` | | 13477 | 30.6% | confirmed |
| **`memories`** `t3605` | | 11972 | 27.2% | confirmed | ← M4 记忆时间线数据源 |
| `focus` `t2c38` | | 5743 | 13.0% | confirmed |

### 3.5 置信度定义

| 级别 | 含义 |
| --- | --- |
| **confirmed** | 字段名来自游戏二进制内嵌的真实令牌表，且在存档中实测命中；值直接取自存档 |
| **inferred** | 值由其他字段推导得出（如反向索引、缺省约定），存档未直接写明 |
| **unresolved** | 键已确认，但值是数字 id，尚无索引可转成可读名。**必须原样保留 id 并标记，不得编造名称** |
| **未验证** | 结构上看似如此，但本轮没有做交叉验证，不作为事实使用 |

---

## 4. 亲子关系：为什么只能反推

### 4.1 事实

- 明文中确实存在 token `father`(`t280c`) 与 `mother`(`t280d`)，各出现 445 次；
- 但它们**不在人物块里**，而是在 `unborn`(`t2a5a`) 容器内——那是**孕期未出生胎儿**的记录：

```
unborn={
    {
        mother=36751
        father=36686
        assumed_father=36686     # t3035
        date=762.8.10            # t06b5，预产期
    }
}
```

- 人物块自身**没有任何指向父母的字段**（`real_father` 除外）。

### 4.2 反推算法

```
对每个人物 P：
    对 P.children 中的每个 id C：
        若 P.female == yes  → C.mother = P
        否则                → C.father = P
    标注 C.parent_source = "child_backref"（推断，非直述）
```

实测结果（44096 人为分母）：

| 结果 | 数量 | 占比 |
| --- | --- | --- |
| 反推出 `father` | 11330 | 25.7% |
| 反推出 `mother` | 5955 | 13.5% |
| 直述 `real_father` | 48 | 0.1% |

一致性校验：`11330 + 5955 = 17285`，与 `child` 关系边总数 `17286` 相差 1
（该条边指向的 id 不在三容器内，属已被彻底剪枝的人物）——数量吻合，算法无系统性丢失。

### 4.3 必须遵守的表达约束

- `father` / `mother` 一律带 `parent_source = "child_backref"`，
  在 UI 与数据契约中按 **inferred** 呈现，**不得**表述为"存档记载其父为 X"。
- `real_father` 是 **confirmed**，与反推出的 `father` **并存**且**语义不同**：
  前者是生父，后者是（法律/名义上的）父亲。私生子场景下两者可能不一致，
  **不得**用任何一方覆盖另一方。
- 若某人的父母未被反推出来，就是**未知**，
  **不得**写成"父母不详"以外的任何叙述，也不得用 LLM 补全。

---

## 5. 尚未解析的值（M2 实体索引的输入）

以下字段的**键**已 confirmed，但**值是数字 id**，当前一律标记 `unresolved`：

| 字段 | 值样例 | 需要的索引 |
| --- | --- | --- |
| `faith` | `23` | 信仰索引 |
| `culture` | `87` | 文化索引 |
| `dynasty_house` | `9039` | 家族分支索引 |
| `traits` | `66 74 62 22 298` | 特质索引 |
| `sexuality` | `1` | 枚举表 |
| `dead_data.reason` | `death_disappearance` | 本地化（是字符串键，非数字） |

> 现阶段这些字段在 `CharacterRecord.evidence_warnings` 中以
> `faith:numeric_id` 之类的条目显式列出。**在 M2 建立实体索引之前，
> 前端只能显示 id 并标注"未解析"，绝不允许显示编造的名称。**

同样地，`primary_title`（`t2828`）这个 token 在本存档中**出现 0 次**——
说明人物块不存储主头衔，头衔归属必须从 `landed_titles`(`t27d6`) 的
`holder`(`t27d7`) / `history`(`t2cd6`) 反向解析。这正是 M3 的任务。

---

## 6. 版本与 Mod 影响

### 6.1 版本漂移

- 令牌表是**版本相关**的：不同 CK3 版本可能新增/移动 token id。
- `extract_tokens.py --verify` 会校验三元锚点
  （`living`/`dead_prunable`/`dead_unprunable` 的 id 必须连续且名称匹配）；
  锚点不成立即判定为不兼容版本并以非 0 退出码失败，**不会**产出可疑的表。
- Rust 侧每个字段键都写成 `&[真实名, 占位token]` 双写法，
  因此**同一套扫描逻辑**对真实表构建和占位表构建都成立；
  CI 用占位表构建（真实表不可分发），本地开发用真实表。
- 本文所有计数均基于 **1.19.0.6**。换版本必须重跑 §1.4 的交叉验证再更新本文。

### 6.2 Mod 影响

- 本存档启用 33 个 Mod，其中包含**自定义开局剧本**（东亚 762 年）。
  因此存档里的人物与游戏自带 `history/characters` 完全对不上
  （抽查 id 6440：游戏历史文件里是法国人 Robert，存档里却是文化
  `asian_han_chinese`、名 `韫秀`、生于 726 年）。
  → **结论：不能用游戏历史文件做人物地面真值**，此路已验证不通。
- Mod 新增的自定义字段会以未知 token 形式出现。当前策略：
  **跳过未识别键，不让单个未知字段导致整个人物档案失败**，
  并在档案级 `evidence_warnings` 中记录，符合 Phase 2B 硬性约束。
- Mod 生成的人物名带机器后缀（`Shunxian_9806_5148`），
  这是 Mod 的命名方式，**原样保留**，不做清洗——清洗即篡改。

---

## 7. 字段研究工具（诊断子命令）

以下子命令用于**后续里程碑继续做字段考古**，不参与正式解析链路。
统一调用格式为 `ck3-reader <子命令> <存档路径> <参数> [--limit N] [--out 目录]`，
报告默认写入 `data/debug/`。

| 子命令 | 用途 | 实测结果（本存档） |
| --- | --- | --- |
| `inspect-token <token>` | 统计某 token 在人物块内的**值类型分布**并抽样 | `t2755` → 命中，类型分布以 `str<N>` 为主 |
| `sample-field <字段>` | 统计某字段的**命中人物数**并抽样若干条 | `first_name` → 44096（100%）；`child` → 9299 |
| `inspect-character <id>` | 导出单个人物块的**字段结构清单**（只出类型不出原文） | `6432`(living) 77 行；`5`(dead_unprunable) 14 行；`1839`(dead_prunable) 14 行 |
| `find-references <id>` | 反查**谁引用了该人物** | `6432` → 5 条（heir / memories / council / council_task / domain） |

`sample-field child` 命中 **9299** 人，与独立 Python 基线 `expect.py` 统计的
"有 child 的人物数 9299" 完全一致 —— 这是对反向亲子索引的一次**独立交叉验证**。

### 7.1 本轮修复的工具缺陷

这四个子命令此前**全部不可用**，本轮一并修复：

1. **参数越界 panic**：四个处理分支都从 `args[4..]` 取参数，
   而入口实际把参数放在 `args[3]`（`args[2]` 是存档路径），调用即 panic。
2. **只认占位令牌形态**：`token_kv()` 只匹配 `tXXXX=` 五字符键，
   `walk_char_blocks()` 硬编码 `t2ce6={`。换用真实令牌表后 melt 输出可读名
   （`first_name=` / `living={`），导致这些工具**扫不到任何内容**。
   已改为 `field_kv()` + `field_matches()` 双形态匹配，
   容器前缀改为六项（三容器 × 真实名/占位名）并容忍缩进
   （`dead_prunable` 嵌在 `characters` 内，是**制表符缩进**的）。
3. **块边界算错**：子块结束判定写成 `d <= char_base`，
   实际应为 `d <= char_base + 1`；原逻辑会让**第一个人物块吞掉整个容器**，
   之后 `depth` 又被错误重置为 `char_base` 而提前退出容器。
4. **性能**：回调内每次都对上百 MB 明文重新 `text.lines().collect()`。
   改为调用方切分一次、复用切片。
5. **死条件**：`find-references` 里 `id_pat.contains(id) == false` 恒为假，
   该分支从不执行；且无法识别跨行数组。已改为按空白切分做**整词匹配**，
   并用 `key_stack` 给跨行数组元素定位归属字段。

---

## 8. 本轮未解决 / 明确的限制

1. `skill`(`t29a5`) 六维的**顺序**未验证，因此暂不对外暴露具体维度名。
2. `t37e7`（38.7% 命中）与 `t0251`=`weight` 的内部结构未细究。
3. 本存档为**开局第 4 天**，统治史/战争/囚禁数据天然稀疏；
   M3–M4 的提取正确性需要另找**中后期存档**复验，否则低计数无法区分
   "提取失败"和"本来就没有"。
4. 头衔（M3）、记忆（M4）、时间线（M5）本轮**未实现**，仅完成数据源定位。
5. 真实令牌表覆盖 8161 个 token；游戏总 token 空间为 65536，
   未覆盖部分以占位符补齐。对本存档覆盖率 100%，但**不保证**对所有存档 100%。
6. `classify_value()` 用**数值区间启发式**（6000–60000）判断"像不像人物 id"，
   会把同区间的其他 id 误标为 `charid`（例如 `dynasty_house=9067` 被标成
   `charid:9067`）。这只影响**诊断报告的可读性**，不影响正式提取链路
   —— 正式链路按字段语义取值，不依赖该启发式。
7. `find-references` 做的是**纯数字整词匹配**，而头衔 / 记忆 / 神器等
   使用各自独立的 id 空间且与人物 id 数值重叠，因此可能出现
   **跨命名空间误报**（如 `domain(array)` 里的 6432 实为头衔 id）。
   在 M2 建立实体索引前，其输出只能当作**线索**而非结论。

---

## 9. 变更索引

| 文件 | 变更 |
| --- | --- |
| `tools/ck3-reader/extract_tokens.py` | 新增：从本机 ck3.exe 提取真实令牌表 |
| `tools/ck3-reader/build.sh` | 优先真实表，缺失回退占位表 |
| `tools/ck3-reader/src/main.rs` | 常量全面改为「真实名 + 占位 token」双写；重写人物扫描（三容器 / 子块 / 列表两种写法）；新增反向亲子索引；删除三条错误 token 假设；修复四个诊断子命令（见 §7.1） |
| `apps/server/app/services/character_extractor.py` | 死亡事件改取 `dead_data/date`（去掉 `9999.1.1` 哨兵）；反推父母标 `inferred` 并产告警；数字 id 明确"不伪造名称" |
| `apps/server/tests/test_character_extractor.py` | 新增 6 例：反推父母 / `real_father` 共存 / 死亡事件取值 / 无日期不造假 / 数字 id 告警措辞 |
| `.gitignore` | 排除 `tools/ck3-reader/tokens/*_real.txt` |
