# Phase 2B M5：时间线去重合并 + 搜索/导入/人名中文化 —— 验收报告

> 日期：2026-08-03 ｜ 提交：本提交 ｜ 前置：Phase 2A / 2A.1 / 2B M1（fa1dfd2）/ M2（3214461）/ M3 / M4
>
> 目标：① TimelineBuilder —— 把记忆/头衔/基础事件统一构建契约时间线并**去重合并**；
> ② 修复用户验收反馈的三类问题 —— 搜索国家和人名不全、导入存档没按 Mock 演示走、
> 识别出来的存档搜不到、外国人名无游戏中文翻译。
> **绝不把模型想象伪装成事实**：合并只针对可证明的重复记录，名字解析全部有据可查。

---

## 1. 分层职责（延续 M3/M4 原则）

| 层 | 职责 | 说明 |
| --- | --- | --- |
| Rust `ck3-reader` | 本轮**未改动** | 数据源（characters/titles/memories）已齐 |
| Python `timeline_builder.py`（新） | 时间线去重合并纯函数 | `merge_timeline(events)` → `TimelineMergeResult(timeline, merged_count, merge_details)` |
| Python `character_extractor.py` | 名字解析增强 + 合并接入 | `resolve_display_name(nk, loader)`（loc→hex→原 key，绝不编造）；`to_profile` 三来源统一走 `merge_timeline` |
| Python `session_manager.py` | 搜索修复 | `q` 匹配解析后字段（名字/头衔/王朝/文化/信仰）；`title=` 按 holder id 集合过滤 |
| Python `routers/saves.py` | 新端点 + loader 修复 | `GET /local-saves/{id}/characters/{cid}/timeline`；loader 缺失时**构建而非只读缓存** |
| 前端 `RealParsePage`（新） | 真实解析过程页 | 初检（inspect）→ Mod 报告（mods）→ 解析（parse melt），真实状态非假进度条 |
| 前端 `TimelineNode` | 合并徽标 | `mergedCount > 1` 显示「已合并 N 条记录」 |

## 2. TimelineBuilder：去重合并（M5 核心）

**根因**：真实存档中 `child_born` + `first_born`/`twins_born` 是对同一孩子、同一日期的**双记忆**，
`MemoryTimelineIndex` 会为同一位家长产出两条 `child_birth` 事件（同一 child id、同一 date），
人物时间线上出现完全重复的条目。抽样 2000 人中 **239 人（11.9%）** 有时间线重复，共 **340 条**重复事件。

**合并规则**（`merge_timeline` 纯函数）：
- 去重键 `(type, date, 首位 relatedCharacter/relatedTitle/location id)`；**无日期事件永不合并**。
- 保留 **id 最小**的事件为主事件；`evidence` 按 id 聚合成并组内全部证据（合并组内 0 缺证据保持 0）；
- `mergedCount = 组大小`（>1 即表示合并过）；合并时在 description 追加
  「（存档另有 N 条重复记录，已合并，证据均已保留）」；返回值附 `merge_details`（每次合并的 key_type/date/primary/merged_ids）。
- **不误合并**：battle/war/title_gain 等仅"类型+日期相同"但实体不同的真实事件，因首实体 id 不同而不合并。

**实测**：全部 `mergeDetails.key_type` 均为 `child_birth`；示例 6438 士准、6440 韫秀、6453 Sabin、
6461 次公（6 事件含 1 合并）、6464 良弓、6466 兰。玩家 12659（理古）4 事件 0 合并（无重复，符合预期）。

**接入**：`to_profile` 原「基础/头衔/记忆三处 `extend` + sort」统一改为三来源拼接后一次 `merge_timeline`。

## 3. 搜索修复（q 匹配解析后字段 + title 过滤）

**根因**：`list_characters` 的 `q` 只在原始 stub JSON 上匹配，而 stub 里 name 是 **key 形态**
（`max_chinese_male_name_117825`、`Zhongrong_4EF2_5BB9`、`Maurizio`），用户搜中文名完全匹配不上；
`title` 过滤参数恒为「全部通过」。

**修复**：
- `q` 改为匹配**解析后字段**：名字经 `loader.resolve`（含 hex 解码）的结果 + 头衔名（title_index）+ 王朝/文化/信仰名。
- 性能：名字解析按需 + 模块级 LRU（name key → 解析名，上限 4096），避免 44096 人重复 resolve。
- `title=` 参数改为按头衔名反查 holder id 集合过滤（`TitleProfileIndex.holder_ids_for_title`，大小写不敏感子串匹配），不再恒通过。

**实测**：`q=李` → **30**（含头衔名 李氏/李坑）；`q=仲容`（hex 解码名）→ **1**；`q=凯热瓦特`（拉丁音译）→ **8**；
`title=幽蓟` → **3**（该头衔现任+过往 holder 过滤生效）。

## 4. 人名中文化（loc → hex → 拉丁音译，绝不编造）

真实存档人物名三种形态，解析顺序 `resolve_display_name`：
1. **loc key**（`max_chinese_male_name_117825`）：`LocalizationLoader` 本地化表解析；
2. **拼音hex**（`Zhongrong_4EF2_5BB9`）：本地化未命中时按 Unicode hex **确定性解码**为汉字
   （`4EF2`/`5BB9` → 「仲容」，与游戏中文显示一致），仅限 CJK 码点，`sourcePath` 标注 `#name_hex_decoded`，非编造；
3. **纯拉丁字符串**（`Maurizio`）：走游戏本地化表音译（`character_names_l_simp_chinese.yml`，11744 行，含 `Maurizio:"毛里齐奥"`）；
4. 全部未命中才回退原 id（不伪造）。

**loader 缺失修复**（用户反馈"识别出来的存档有些搜不到"的关键 bug）：`character_profile_endpoint` /
`list_characters_endpoint` 用 `_loc_cache.get((save_id, signature))` 取 loader，缓存未命中
（重启后/直接进 URL）时 loader=None → 名字完全不解析显示原 key。改为缺失时**构建**（复用
`_build_localization`），并统一 `_ensure_loader` 入口；`_search_name_cache` 在存档变更/设置变更/删除时清空。

**names 子目录**：`LocalizationLoader.load_dir` 的 `**/*.yml` 覆盖 `game/localization/simp_chinese/names/`
（实测 `Maurizio:"毛里齐奥"` 存在），补单测锁定。

**实测**：`Hua_83EF`→「华」、`Zhongrong_4EF2_5BB9`→「仲容」、`Maurizio`→「毛里齐奥」；
真实存档首屏解析名：凯热瓦特 / 库妮娅夫卡 / 哈德马尔 / 安塞尔姆 / 磨延啜 等，玩家 12659 →「理古」。

## 5. 导入/解析过程页（前端，对齐 Mock 演示）

- 新路由 `/saves/:saveId/parse` → `RealParsePage`：复用 Mock ParsePage 的视觉与阶段状态机
  （pending/running/success/error/skipped），但阶段由**真实后端**驱动：
  ① 初检（`inspect`）→ ② Mod 报告（`mods`，含本地化加载）→ ③ 解析（`parse`，一次 melt + 索引）。
  成功切换真实模式 + 激活存档 + 朱砂落印后进入人物选择页；失败在阶段标注错误、后续阶段 skipped，可重试。
- `LocalSavesPanel`：「解析」按钮与「手动导入成功后」均跳 `/saves/:saveId/parse`（不再直接跳选择页）。
- `TimelineNode`：`mergedCount > 1` 显示「已合并 N 条记录」金色徽标（带 tooltip）。

## 6. 验证结果（全绿基线）

- Rust：`cargo fmt --all -- --check` 0 / `cargo clippy --release -- -D warnings` 0 / `cargo test --release` **20 passed**（本轮未改 Rust，回归全绿）。
- 契约 `save-schema`：**27 passed**（`TimelineEvent.mergedCount` 双端 roundtrip）。
- 后端 pytest：无真实存档 **171 passed / 13 skipped**；真实存档（`SHIGUAN_TEST_SAVE`）**184 passed / 0 skipped**。
- 前端：`tsc --noEmit` 0 错 / `npm run lint` 0 错 0 警告 / `vitest` **132 passed** / `vite build` 成功。
- 真实存档实测：
  - 去重合并：抽样 2000 人 **239 人（11.9%）** 有重复 → 合并后同键重复 **0**，证据 0 缺；
  - 搜索：`q=李`→30、`q=仲容`→1、`q=凯热瓦特`→8、`title=幽蓟`→3；
  - 名字中文化：`Hua_83EF`→华、`Zhongrong_4EF2_5BB9`→仲容、`Maurizio`→毛里齐奥（单测）、玩家 12659→理古；
  - loader 缺失重建回归通过（重启/直达 URL 名字仍中文）。

## 7. 当前限制与下一轮建议

- **限制**：`enum_resolved` 仍仅在明文存档为 true；真实 token 表下 enum 值（faith/dynasty 等）仍为数字 id
  （中文化需 M3.2 之后完整本地化映射）；battle/war 事件不合并（非重复，属正确语义）；地图 / 家族树 / LLM 传记正文未做。
- **下一轮建议**：M5.2 真实关系字段对比（把 became_* 日期配对推断与记忆 participants 角色表交叉验证）；
  或直接进入 Phase 3 LLM 传记管线（八步：解析→索引→档案→时间线→压缩→提纲→正文→事实校验，两次模型调用）。
