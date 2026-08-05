# Phase 3C-Audit：CK3 存档数据源审计报告

> 结论先行：**当前缺失的信息绝大部分是「存档本身没保存」或「reader 曾丢失、现已修复」，
> 而不是 CK3 存档里存在但 SHIGUAN 无法获得。primary_title / 战争→领土绑定属于
> SAVE_ABSENT，任何 reader 都不可能从存档读出来；称谓依赖 Mod 游戏定义文件
> （MOD_REQUIRED），Bridge Mod 亦无法改变这一点。** 本轮不需要 Bridge Mod。

- 审计存档：`593a2ec6a662c1dd.ck3`（TextZip，游戏 1.19.0.6，存档日期 956.12.28，玩家「王，梁克贞」）
- 对照项目：CK3-history-extractor（TCA166，MIT，克隆于 `data/audit/reference/`，不随仓库分发）
- 方法：**一次** `ck3-reader prepare --with-melted`（单次 melt），全部原始取证与对照在
  同一 melt 目录内完成；审计脚本 `scripts/audit_ck3_history_sources.py`，运行产物
  `data/audit/<timestamp>/`（已被 `.gitignore` 忽略，含 melted 原文，绝不分发）。
- 复用方式：`python scripts/audit_ck3_history_sources.py --save-id <id>`，默认自动挑选
  staging 下最新的 `*.ck3`。

---

## 一、审计结论（分类汇总）

| 结论 | 含义 | 数量 | 代表项 |
| --- | --- | --- | --- |
| SAVE_PRESENT | 存档确有，SHIGUAN 已读取 | 19 | history（含显式 type）、holder、title_name_data、name/birth/father/… |
| SAVE_ABSENT | 存档本身没保存 | 5 | primary_title、held_titles、title_liege、war→title 直接绑定 |
| READER_DROPPED | 存档有，reader 未读取 | 11 | capital、claims、de_jure_liege、history_government、landless、court_data、**was_player**、government |
| SEMANTIC_UNUSED | 已读取，语义层未消费 | 4 | traits、de_facto_liege、dead_data、landed_data.domain |
| MOD_REQUIRED | 需 Mod 游戏定义文件才能得出 | 1 | title_history_names（历史称谓） |
| EXTERNAL_TOOL_INFERRED | 仅对照工具默认推断，非存档事实 | 1 | 裸 `date=ID` → 对照项目默认「Inherited」 |
| UNKNOWN | 证据不足 | 4 | law / nickname / coat_of_arms / development 在头衔容器中缺席 |

**关键数字（一次 melt 内的原始取证 vs reader 输出）**：

| 数据 | 存档原始 | SHIGUAN reader | 对照项目口径 |
| --- | --- | --- | --- |
| landed_titles 头衔块 | 19,197 | 19,197 | — |
| title history 总条数 | **34,713** | **34,713**（修复后；修复前仅 13,173，丢 62%） | 保留全部（含默认推断） |
| history 显式 type 条数 | **11,029** | 11,029（`raw_type` 原样保留） | type 原样保留 |
| 人物总数 | 62,564（living 35,476 + dead_unprunable 20,054 + dead_prunable 0） | 62,564 | — |
| 记忆（character_memory_manager.database） | 69,903 条 / 166 类 | 69,903 条 / 166 类（类型零缺失） | 覆盖相似 |
| 战争（wars.active_wars） | 107 | —（本审计未进语义层） | — |

---

## 二、问题逐条回答（对照用户交接文档的 8 个核心问题）

### ① title history 原始 type（conquered / conquest_* / usurped / inherited / created / destroyed / granted…）

- **存档中存在**（SAVE_PRESENT），且 type 全集比文档列举的更大：
  `created`(1498)、`destroyed`(923)、`appointment_succession`(4384)、`migration`(1442)、
  `granted`(1096)、`conquest`(613)、`appointment`(387)、`revoked`(276)、`stepped_down`(182)、
  `conquest_populist`(97)、`abdication`(50)、`conquest_claim`(35)、`faction_demand`(12)、
  `swear_fealty`(8)、`independency`(5)、`leased_out`(4)、`returned`(2)、`conquest_holy_war`(15)。
- **存档中不存在** `usurped` / `inherited` 这两个 type：CK3 引擎写入 history 时并不用它们。
  对照项目对**裸 `date=HOLDER_ID`**（本存档 23,684 条）默认解释为 `Inherited`
  （`title.rs` 第 116 / 139 行），属 **EXTERNAL_TOOL_INFERRED，不是存档事实**——SHIGUAN
  不采信，裸条目保留 `raw_type=None` 由语义层诚实留空。
- **SHIGUAN 曾丢失，已修复**（本轮最小修复）：
  - 旧 reader 把显式 type 折叠成 `created/destroyed/other` 三档，原始字符串被丢弃
    → **READER_DROPPED**。现已原样保留为 `raw_type`（`CACHE_SCHEMA_VERSION=3`）。
  - 旧 reader 的 Format A 解析在读完 `date=HOLDER_ID` 后跳到**行尾**，明文存档把多条
    history 写在同一行时会把后续条目吞掉 → 34,713 条只读到 13,173 条（丢 62%）。
    已改为从数字后继续扫描下一条目，修复后 34,713 = 34,713 完全一致（Rust 单测
    `scan_titles_same_line_format_a_does_not_swallow_next_entry` 覆盖）。
- 对照项目排序：`title.history.sort_by(|a,b| a.0.cmp(&b.0))` 是**升序**（注释却写 descending），
  `get_holder()` 取 `history.last()`；SHIGUAN 取「顶层 holder + 日期数值排序」，无此坑。

### ② SHIGUAN 是否在 reader / normalizer 中丢失

- reader：见上（raw_type 折叠 + Format A 行尾吞条），**均已修复并验证**。
- normalizer：旧 `AcquisitionCauseResolver` 只认 `kind=created` 为「创建」，其余一律
  UNKNOWN 并输出「不得推断」约束——这是**诚实收口而非丢失**（当时 reader 没有 raw_type）。
  本轮 normalizer 已升级：命中 `raw_type` 映射（conquest*/granted/created/usurped→对应
  cause，标 `type_source=save_explicit`），未映射的显式 type 保留原始值并继续诚实留空。

### ③ CK3-history-extractor 是否用默认推断

- **是**。裸 `date=ID` 一律 `GameString::from("Inherited")`；且它把 `held_titles` 等
  按 block 结构解出后交「时间线」模块用 `USURPED_STR`/`CONQUERED_START_STR` 等**启发式**
  匹配历史 type 文本。凡此皆属 **EXTERNAL_TOOL_INFERRED**，不得当存档事实。

### ④ primary title 是否存在于存档

- **否（SAVE_ABSENT）**。全存档（130 MB melt 原文）中 `primary_title=`、`held_titles=`
  出现次数为 **0**；人物块与头衔块都没有这两个字段。CK3 把「当前持有领地」写为
  `landed_data.domain = { 领地 id 列表 }`（人物侧）与 `landed_titles` 顶层 `holder`
  （头衔侧）的**互为反查**，存档从不冗余保存「最高头衔」。
- 推论：primary title 只能由语义层从 holders / domain **推导**（按 tier 最高、或
  de_facto_liege 为空者），推导结果必须标 `inferred`；任何 reader 都无法直接读它。

### ⑤ 称谓（节度使 / 唐皇帝等）来自存档还是 Mod 文件

- 存档只保存**运行时名**：`title_name_data = { name = "…" }`（本存档已读取，中文名如
  `安南`、`大理`）与 `title_history_names`（历史名快照）。
- **「节度使」「唐皇帝」这类称号并不在存档里**：它是 Mod 的
  flavorization（`title_flavorization`）+ localization + customizable_localization 在
  运行时计算出的**动态称谓**。存档里只有 `title_name_data.name` 一个字符串，且不同
  Mod 覆盖下名字可变 → **MOD_REQUIRED + DYNAMIC_UNRESOLVED**。
- SHIGUAN 现有读取：`title_name_data.name`（SAVE_PRESENT）+ 本地化表解析已覆盖存档内
  名字；历史/正式称号需读游戏 Mod 定义文件（`game_data_resolver` 已有 Mod 路径能力，
  留作 3C 后续）。**Bridge Mod 无法把「不存在的字段」写进存档。**

### ⑥ 战争与领土转移是否有直接关联

- **否（SAVE_ABSENT）**。`landed_titles` 容器中 `war_id=` / `won_war=` / `lost_war=` /
  `war=` 出现次数均为 **0**；history 条目里没有 war 引用。
- 战争的唯一显式信号：history type 为 `conquest*`（conquest / conquest_claim /
  conquest_populist / conquest_holy_war，合计 760 条）——表示「因战争获得」，但**不记录
  是哪场战争、对手是谁**。战争本体在 `wars.active_wars`（本存档 107 场，含 attacker /
  defender / casus_belli / battle_results），war→title 的桥不存在。
- 现有近似：M4/2C 已把 `war_won`(869) / `war_lost`(694) / `offensive_war`(937) /
  `joined_allys_war`(1179) 等记忆按主体角色表归属进时间线；与 `conquest*` history 的
  因果匹配只能按日期邻近做**推断**并标 `inferred`，不得写成确定事实。

### ⑦ 记忆参数是否可用于确定因果

- 记忆（`character_memory_manager.database`，69,903 条 / 166 类）含 `type` / `params` /
  `participants`（role 表）/ `dates`（创建/结束）；raw 与 reader 类型普查**完全一致**
  （0 缺失 0 多余），M4 的归属/推断规则已覆盖。war 类记忆可提供「时间 + 对手」，
  `conquest*` history 可提供「哪块地 + 何时」——两者可**推断性**拼接，不能确定因果。

### ⑧ 其他已确认的数据损失点（READER_DROPPED，本轮**不做**大改）

| 字段 | 位置 | 出现次数 | 用途建议 |
| --- | --- | --- | --- |
| `capital` | 头衔块顶层 | 19,182 | 首都/权力中心（P1） |
| `claims` | 头衔块（嵌套） | 1,353 | 宣称（P1） |
| `de_jure_liege` | 头衔块顶层 | 15,942 | 法理上级（P1） |
| `history_government` | 头衔块顶层 | 2,947 | 政体沿革（P1） |
| `de_jure_vassals` | 头衔块 | 有 | 法理封臣（P1） |
| `landless` | 头衔块顶层 | 有 | 无地头衔（P2） |
| `government` | 头衔块/人物块 | 2,947 | 政体（P2） |
| `court_data` | 人物块 | 有 | 宫廷/职务（P2） |
| `was_player=yes` | 人物块 playable_data | 1 | **玩家唯一标记**（P1：`player_id` 现为空） |
| `landed_data.domain` | 人物块 | 有 | 持有领地 id 列表（当前经 holder 反查，SEMANTIC_UNUSED） |

---

## 三、修复优先级

### P0 —— 已随本审计落地（不改语义，只保住原始证据）
1. Rust reader `parse_title_history`：
   - Format B 保留显式 `raw_type`（不再折叠丢弃）；
   - Format A 不跳行尾，同行多条目全部捕获（34,713 条完整恢复）；
   - `CACHE_SCHEMA_VERSION` 2 → 3（旧缓存自动失效重建）。
2. 契约：`HistoricalSemanticEvent.acquisitionRawType` / `acquisitionTypeSource`
   （py+ts 双端镜像 + `AcquisitionTypeSource` 枚举 + 契约测试）。
3. Normalizer：`AcquisitionCauseResolver` 用 `raw_type` 映射（conquest*→CONQUEST、
   granted→GRANT、created→CREATION、usurped→USURPATION，标 `save_explicit`）；未映射
   显式 type 保留原值 + 继续「不得推断」；旧缓存回退 `kind`（标 `reader_default`）。
4. 审计脚本 + 链路测试（`apps/server/tests/test_audit_ck3_history_sources.py` 14 项）。

### P1 —— 建议下一轮（均 READER_DROPPED，且对传记有直接价值）
- `was_player`：唯一玩家标记 → 后端 `player_id` 不再置空（现为 None）。
- `capital` / `claims` / `de_jure_liege` / `history_government` / `de_jure_vassals`
  读取进契约（`CharacterProfile` / `TitleProfileIndex`）。

### P2 —— 低优先
- `landless` / `court_data` / `government` 读取；
- primary_title：确认 SAVE_ABSENT 后由语义层从 holders/domain 推导（必须标 `inferred`）。

---

## 四、是否需 Bridge Mod —— 结论：**不需要**

| 缺失项 | 分类 | Bridge Mod 能否解决 | 说明 |
| --- | --- | --- | --- |
| history 原始 type | SAVE_PRESENT（曾 READER_DROPPED） | 不需要 | reader 已修复并保留 `raw_type` |
| primary_title | SAVE_ABSENT | 不能 | 存档不写该字段；只能推导 |
| 战争→领土绑定 | SAVE_ABSENT | 不能 | 存档不写 war_id；只能按 conquest* + 日期推断 |
| 称谓（节度使/唐皇帝） | MOD_REQUIRED | 不能 | 是游戏定义/本地化层的动态产物，不在存档里 |
| usurped/inherited type | EXTERNAL_TOOL_INFERRED | 不需要 | CK3 不写这两个 type；对照项目才默认推断 |

Bridge Mod 只有在下述情况才有价值：**需要把「游戏只在内存中知道、从不落盘」的信息在
存档写入瞬间注入**（如 war→title 绑定）。但：① 存档历史写入由引擎闭包完成，Mod 事件
脚本无法在历史条目里插入 war 引用；② 即便能，也会污染存档、破坏「存档即证据」的
取证性；③ 现有 `conquest*` type + 战争记忆已提供足够近似。故**维持不实现 Bridge Mod**。

---

## 五、限制与诚实边界

- 本审计只覆盖一个存档（梁克贞 956.12.28）；字段存在性结论以「一次 melt 原始文本
  探测」为准，个别字段可能随存档/版本变化（如 `dead_prunable` 容器在本存档为 0）。
- `mother=` 直接字段在人物块中为 **0 处**：母系亲缘靠「其他角色的 child 列表反推」
  （reader `parent_source=child_backref`）与记忆 params 引用（828 处）获得——推导关系
  在展示时必须标注来源，不得写成直述。
- 死亡日期存于 `dead_data.date`（非 `death=` 键），reader 已读取；`death=` 全局仅 1 处。
- `raw_type` 只在 v3 缓存（CACHE_SCHEMA_VERSION=3）之后产生；旧缓存会整体失效重建，
  服务重启后自动生效，无兼容性风险。
- 对照项目为 MIT 许可，仅作口径对照；其默认推断（Inherited）与启发式匹配一律不采信。

## 六、下一轮建议

1. P1 落地：`was_player` 读取修复 `player_id`；`capital/claims/de_jure_liege/history_government`
   进契约（reader + models.py/types.ts 双端同步 + 契约测试）。
2. 语义层把「raw_type=conquest*」+ 记忆 `war_won/lost`（时间邻近）拼成「经战争获得，
   对手疑为 X」的 **inferred** 事件（带 EvidenceRef 双源，仍不写死因果）。
3. 称谓收尾：接 `game_data_resolver` 读 Mod flavorization 定义，对 `title_name_data.name`
   命中的动态称谓做「存档名 + 定义名」双栏展示，缺定义时诚实只显示存档名。
4. 将本审计接入 CI：无真实存档时仅跑解析器单测（现有 14 项），有样本时跑全量对照。
