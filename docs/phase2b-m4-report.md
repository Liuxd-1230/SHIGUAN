# Phase 2B M4（#120）：关系 · 特质 · 记忆深化 —— 验收报告

> 日期：2026-08-03 ｜ 提交：本提交 ｜ 前置：Phase 2A / 2A.1 / 2B M1（fa1dfd2）/ M2（3214461）/ M3
>
> 目标：#120「关系特质记忆深化」—— 从 `character_memory_manager.database` 反解记忆库，
> 归属到人物并映射为契约 `CharacterProfile.memories` / 时间线事件 / 好友·宿敌·恋人关系；
> 同时扫描婚姻历史 6 字段（former_spouses/betrothed/concubine/concubinist/former_concubinists/former_concubines）
> 与共享父母推导的兄弟姐妹。**绝不把无法证明的归属伪装成事实**。

---

## 1. 分层职责（延续 M3 原则）

| 层 | 职责 | 说明 |
| --- | --- | --- |
| Rust `ck3-reader` | 只从 melt 明文抄 **存档内部键**，不做本地化 | `scan_memories` → `memories.json`（id / type / participants 角色表 / creation_date / end_date / battle_location_id）；`scan_characters_full` 增 6 婚姻历史字段 |
| Python `MemoryTimelineIndex` | 记忆归属 + 关系推导 + 告警 | 主体角色归属表 + family_data 交叉核对 → `CharacterProfile.memories` + 时间线事件 + friends/rivals/lovers |
| Python `CharacterExtractor` | 婚姻历史语义化 + 兄弟推导 | `spouses: RelationshipPeriod[]`（含 isFormer / betrothed / concubine）、`siblings`（共享父母 + 推断标注） |
| Python `saves.py` | `GET /local-saves/{id}/characters/{cid}/memories` | 与档案页共享同一记忆索引缓存，**一次 melt，多次查询** |
| 前端 `MemoriesPanel` | 关系 chips + 按日期排序记忆列表 | 空态 / 降级 / “推断”徽标，对齐 M3 TitlesPanel |

## 2. Rust：`scan_memories`（memories.json）

- 容器定位：`character_memory_manager.database` 内层块；外层 manager 块也可能以 token 形态出现，
  用双 token 形态匹配（`find_container_block` 支持字面名与 token 名）。
- 每条记忆：
  - `id`（全局计数器，**不可解码 owner**——本项目的关键边界，见 §3）；
  - `memory_type`（如 `married` / `child_born` / `became_friends` / `battle_won_memory`）；
  - `participants: [{role, character_id}]`（married 只列对方 `spouse`；battle 记忆含 `ruler`/`loser`/`winner`）；
  - `creation_date` / `end_date`（部分条目缺失，容忍）；
  - `battle_location_id`（从 `variables.flag=="battle_location"` 块的 `identity=` 抓取，用于战役位置展示）。
- 空条目 `NUMBER=none`（28674=none 标量槽）跳过；容器缺失 → `warnings: ["container_not_found: ..."]`，不静默为空。
- 单测 4 项：结构解析（含 battle location）、缺失日期容忍、容器缺失告警、token 形态容器。

## 3. Python：`MemoryTimelineIndex`（归属规则，诚实性优先）

**关键事实**：记忆 key 是存档级全局计数器，无法解码 owner。实测 married 记忆**按夫妻成对生成**
（每对夫妻各一条、互指对方为 spouse），因此用「主体角色表 + family_data 交叉核对」归属：

1. **family_data 交叉核对（owner 在条目外）**：married 记忆只列对方，用“谁的 spouse 列表含该
   participant”判定 owner；child_born / first_born / twins_born 同理（谁的 children 列表含 child，
   另补子嗣 stub 直述的 father/mother）。**实测 6543 条 married 记忆，6498 条（99.3%）可归属**；
   归属不上的按条目中指名人物记录并产生 `memory_owner_unresolved` 告警（不伪造）。
2. **主体归属（owner 不可解时）**：became_*（new_soulmate/new_relation/rival）、*_died
   （dead_relation）、battle_*（ruler）、war_*（winner/loser/other_party）的“被点名者”即主体，直接归属。
3. **诚实跳过**：`imprisoned` / `ascended_throne_memory` / `released_from_prison_memory` /
   `lost_title_memory` 的 owner 非 participant 且主体语义不明 → 不进时间线、不进个人归属，
   只计入 `skippedTypeCount`（不编造归属，如实披露局限）。
4. **时间线事件**：仅「有日期 + 可归属 + 映射到契约事件类型」的条目生成（marriage / child_birth /
   death / war），全部带 `sourceType="memory"` 的 `EvidenceRef`，**0 事件缺证据**；无日期只进
   `memories` 原始列表，不伪造事件。

**关系推导（好友/宿敌/恋人）**：became_* 记忆按“事件双方各一条、互指对方”成对生成
（实测 became_soulmates 11 个日期中 10 个成对）。因此**同类型 + 同 creation_date + 恰好两条 +
主体互异 → 推断两条主体互为好友/宿敌/恋人**；该推断标 `INFERRED` 并附
`relationship_inferred_from_memory` 告警。配对不上的单条记忆只进 memories 列表、
以 `friendCount/rivalCount/loverCount` 计数呈现——**对方未指名，不伪造名字**。

**名字解析**：全部经会话人物索引 stub → 本地化名；查不到 → `name=原始 id`、`resolved=False`（不编造）。

## 4. 婚姻历史与兄弟姐妹

- `scan_characters_full` 增 6 字段（双 token 形态，沿用 M1 模式）：`former_spouses`(t3241) /
  `betrothed`(t2bb9) / `concubine`(t2bd3) / `concubinist`(t336e) / `former_concubinists`(t33a2) /
  `former_concubines`(t33a3)；其中 former_* 与 concubine 支持块列表与标量多行两种写法。
- Python `CharacterExtractor`：`spouses: RelationshipPeriod[]` 语义化为
  **spouse（现任）/ former_spouses（`isFormer=true`）/ betrothed（`type="betrothed"`）/
  concubine+concubinist（`type="concubine"`）/ former_concubines+former_concubinists
  （`type="concubine"` + `isFormer=true`）**；名字经会话索引解析，不再裸 id。
- `siblings`：共享父母推导（同 father 或同 mother），`sourcePath` 带
  `#inferred_from_shared_parent` 标注（推断而非存档直述，但父母关系本身为存档直述）。
- 契约微调（双端同步 + 契约测试）：`RelationshipType` 增 `betrothed` / `concubine`；
  `RelationshipPeriod.isFormer?: boolean`。

## 5. 端点与前端

- `GET /api/local-saves/{save_id}/characters/{character_id}/memories` 返回
  `{saveId, characterId, memoryCount, skippedTypeCount, memories, relationships{friends,rivals,lovers,friendCount,rivalCount,loverCount}, warnings}`；
  档案页与 memories 端点共享 `_memory_index` 缓存（`_memory_index_cache`，saveId 隔离，watch/删除/设置变更时清空），
  **不重复扫描 memories.json，不重新 melt**。
- 前端 `MemoriesPanel`：配偶/婚约/妾室语义 chips（前配偶 / 前妾室 标注 isFormer）、兄弟姐妹 /
  好友 / 宿敌 / 恋人分组（计数 + “推断”徽标，仅 became_* 配对项标推断）、记忆列表按 CK3 日期升序
  （未知日期排最后）、未解析人名（name==id）标“（未解析）”、空态诚实文案；挂载于
  `BiographyPage`（M3 TitlesPanel 之后）。

## 6. 验证（全绿）

| 项 | 结果 |
| --- | --- |
| Rust `fmt --all -- --check` | 0 |
| Rust `clippy --release -- -D warnings` | 0 |
| Rust `test --release` | **20 passed**（M3 16 + M4 scan_memories 4） |
| 契约 `save-schema` | **26 passed**（betrothed/concubine + isFormer 双端一致） |
| 后端 pytest（无真实存档） | **153 passed / 9 skipped**（真实集成无样本跳过，CI 友好） |
| 后端 pytest（真实存档 `SHIGUAN_TEST_SAVE`） | **163 passed / 0 skipped**（含 `test_character_memories`、`test_character_titles`、婚姻历史字段实测） |
| 前端 tsc | 0 错 |
| 前端 eslint | 0 错 0 警告 |
| 前端 vitest | **122 passed**（新增 `MemoriesPanel.test.tsx` 5 项；`BiographyPage` 12 项保留） |
| 前端 vite build | 成功（438 模块） |

> `test_api.py` 新增 `test_character_memories`：真实存档集成，校验 12659/9536 夫妻互证记忆、
> isFormer 语义、6039 恋人含 4927 号日期配对推断、全部时间线事件带 EvidenceRef、skippedTypeCount > 0。
> `test_routing_api.py` 新增 `test_m4_memory_paths_do_not_leak_local_paths`：响应不含本地绝对路径。

## 7. 真实存档实测（`SHIGUAN_TEST_SAVE` = 本机 62MB 存档，1.19.0.6，真实 token 表）

- `memories.json`：**28675 条记忆、116 种类型**、Rust 扫描告警 0；Top 类型：married **6543**、
  child_born 2994、ascended_throne_memory 2965、first_born 2317、became_friends 1729、
  relative_died 1081、became_rivals 1028、battle_won_memory 1015、battle_lost_memory 976…
  （2026-08-03 重新跑 `test_character_memories` 后从缓存复算）。
- married 归属：**6543 条中 6498 条（99.3%）**经 family_data 交叉核对归属成功，失败 45 条
  按条目指名人物记录并产生 `memory_owner_unresolved` 告警（如实披露）。
- 关系成对推断（同类型 + 同 creation_date + 恰两条 + 主体互异）：
  became_soulmates 21 记忆 / 11 日期 / **10 成对**；became_lovers 305 / 139 / **113 成对**；
  became_friends 1729 / 662 / **444 成对**；became_rivals 1028 / 399 / **289 成对**。
  未成对的单边记忆按 `*Count` 计数呈现（对方未指名，不伪造名字）。
- 诚实跳过：imprisoned 594 / ascended_throne_memory 2965 / lost_title_memory 585 /
  released_from_prison_memory 等 **skippedTypeCount = 4572**（owner 非 participant，不归属不编造）。
- 婚姻历史字段（真实存档计数精确）：12659 的 `spouses=[9536, 43537]`、
  `former_spouses=[9536]` → 档案 `spouses` 中 9536 `isFormer=true`、43537 非 former；
  六字段（former_spouses/betrothed/concubine/concubinist/former_concubinists/former_concubines）全部扫到实际条目。
- 样本人物：**12659** 归属 3 条记忆 + 3 条时间线事件（marriage），**0 事件缺 EvidenceRef**；
  **6039** 由 became_lovers 日期配对推断出 **4927** 为恋人（标 INFERRED + 告警）；
  随机 200 人物抽样时间线事件 **0 缺证据**。
- 名字解析：真实 token 表 + 本地化表下输出中文人名；未解析 id 回退 `name=id` 不伪造。

## 8. 边界与后续

- **owner 不可解码**：记忆 key 是全局计数器，任何声称“这条记忆属于谁”的判定都只能靠
  family_data 交叉核对（99.3%）或主体角色推断；剩余的诚实跳过并计数。
- **became_* 关系是推断**：同类型同日期恰两条 + 主体互异才进 friends/rivals/lovers 并标
  INFERRED；单条记忆只计数不命名。存档若有直接关系字段（如真实 rival 列表）可在 M5 接入对比。
- **特质**：名称本地化可用（genius 等），但 category 无可靠数据源、trait_gain 无日期——
  本轮不编造，未扩展。
- **battle_won_memory 本地化模板**：清洗为安全文案（不渲染 `[ROOT.Var...]` 占位符），
  位置以 province id 呈现（`resolved=false`，无地名映射不伪造）。
- 下一轮建议：M5 TimelineBuilder（把记忆时间线事件正式接入契约时间线并去重合并）、
  M5.2 真实关系字段（rival/friend 列表）与推断关系对比、或 Phase 3 LLM 传记生成。
- 地图 / 家族树仍属范围外。
