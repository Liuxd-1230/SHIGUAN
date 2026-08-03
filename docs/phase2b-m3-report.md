# Phase 2B M3（#119）：头衔与统治经历 —— 验收报告

> 日期：2026-08-03 ｜ 提交：本提交（commit hash 见 git log / 推送记录）｜ 前置：Phase 2A / 2A.1 / 2B M1（fa1dfd2）/ M2（3214461）
>
> 目标：#119「头衔与统治经历」—— 从 `landed_titles` 反向解析每个角色的现任头衔与历史任职段，
> 输出契约 `TitlePeriod[]`；名字解析遵循「存档直书 → 实体索引 → 本地化 → key 回退（不伪造）」。
> 同时真实集成测试暴露并修复了 M2 的一处路由回归与一处字段提取 bug（见 §4）。

---

## 1. 分层职责（延续 M2 原则）

| 层 | 职责 | 说明 |
| --- | --- | --- |
| Rust `ck3-reader` | 只从 melt 明文抄 **存档内部键**，不做本地化 | `scan_titles` → `titles.json`：key / name / name_source / tier / holder_id / de_facto_liege_id / history |
| Python `TitleReignExtractor` | 聚合单角色头衔段 + 名字解析 | 现任头衔 `isCurrent=True`、过往任职段（start, end）、名字解析链 |
| Python `TitleProfileIndex` | 一次性反解全部头衔 → 单角色查询 | primaryTitle / highestTitleTier / isRuler / ruler_ids / 证据告警 |
| Python `GameDefLoader` + `LocalizationLoader` | def 键 → loc 键 → 可读名 | 缺失降级，不阻断 |
| `ReferenceResolver` | 实体索引查名 | 未命中 `name=原id` / `resolved=false`，**绝不编造** |

## 2. Rust：`scan_titles`（titles.json）

- 容器定位：`landed_titles.landed_titles` 内层块（外层是存档总键，内层才是标题表）。
- 每条头衔：
  - `key`（如 `k_papal_state`）、`name`（`title_name_data.name`，真实存档为中文）、`name_source`（save / key / unresolved）；
  - `tier`：由 key 前缀推导（b/c/d/k/e/h → barony/county/duchy/kingdom/empire/empire；未知 → unknown，不硬造）；
  - `holder_id` / `de_facto_liege_id`：**只取 history 块之前的顶层字段**——history 内 Format B 也含 `holder=`，全块搜索会误抓历史持有者（注释 + 单测锁定）；
  - `history`：按日期排序的持有者变更记录，双格式：
    - Format A：`date=HOLDER_ID` → `{date, holder_id, kind:"holder"}`
    - Format B：`date={ type=created/destroyed holder=ID }` → `{date, holder_id, kind:"created"/"destroyed"}`
- 日期排序用数值 `(年,月,日)` 键（CK3 日期未零填充，字符串排序会错）。
- 容器缺失 → `warnings: ["container_not_found: ..."]`，不静默为空。

## 3. Python：`TitleReignExtractor` + `TitleProfileIndex` + 端点

- `_reign_runs(history, cid)`：把 holder 连续同值段聚合为 `[(start, end)]`；end=None 表示开放段；
  `destroyed`（holder=None）正确断段。
- `extract(raw_titles, cid)` → `TitlePeriod[]`：
  - 现任（顶层 `holder_id==cid`）且 history 有对应段 → `isCurrent=True, end=None`；
  - 现任但 history 无该角色段（如 history 空）→ `start=None`，诚实留空；
  - 过往任职 → `isCurrent=False`，end 为下一变更日；
  - 排序：未知 start 排最后，其余按 CK3 日期数值升序。
- `TitleProfileIndex`：一次性 `_build()` 反解全部头衔（当前存档 19003 条），提供
  `periods(cid)` / `warnings(cid)` / `ruler_ids()` / `primary_bits(cid)`；primary 规则：
  最高等级且 `isCurrent=True` 取现任段，否则取最后一次任职；同级多头衔 → `primary_title_inferred`
  告警并取现任段最后一段；无任一段 → `primary_title_unresolved`，摘要不写死任意头衔。
- 名字解析顺序：`name_source=="save"` 直书可读名 → `ReferenceResolver.resolve("title", key)`（实体索引，可能含 loc/def 解析名）→ `LocalizationLoader.resolve(key)` → 回退 `name or key`（不伪造）。
- 端点 `GET /api/local-saves/{save_id}/characters/{character_id}/titles` 返回
  `{saveId, characterId, titles: TitlePeriod[], warnings}`；未命中人物 → 空列表（不 404）。
- `CharacterProfile.titles: TitlePeriod[]` 与 `CharacterSummary` 的
  `primaryTitle / highestTitleTier / isRuler / warningCount`：单人物档案按需从同一份索引取，
  **不重复 melt、不重复扫描明文**（满足"一次 melt，多次查询"）。

## 4. 真实集成测试暴露并修复的回归（重要）

M3 在**本机真实存档**上跑通 `test_character_titles` 时，连带发现并修复以下问题：

1. **M2 路由回归（最严重）**：`3214461` 编辑 entities 端点时**误删了 `parse_save_endpoint` 的 `@router.post` 装饰器**，
   `POST /api/local-saves/{id}/parse` 在 HEAD 上返回 FastAPI 默认 404。此前真实集成测试在无 reader/存档环境整体跳过
   （CI 无真实存档），导致回归未被发现。修复：补回装饰器 + 新增 `test_critical_routes_registered`（遍历
   `_IncludedRouter.original_router.routes` + prefix，断言 12 个关键端点及方法集合，CI 无 reader 也必跑）。
2. **`game_version` 提取 bug**：`extract_field` 用子串 `find`，`save_game_version=15` 含子串 `version`，
   把 `game_version` 误填为存档格式版本 15（应为 `"1.19.0.6"`）。修复：改**整词匹配**（trim 后行首键全等），
   meta_data 顶层均为 `key=value` 行，安全。→ inspect / parse 的 `game_version`、版本兼容性判断恢复正确。
3. **trait 名解析 None**：`loader.resolve(t)` 对本地化表未收录的 trait 返回 None → `TraitRecord.name` 契约非空校验失败。
   修复：查不到回退原 id（与 `_entity_ref_for` 一致，不伪造）。
4. **缓存无版本门槛**：meta.json 增加 `reader_version` 字段（Rust 写入）；Python `_cache_valid` 要求其存在，
   旧版缓存（含上述错误数据）自动失效重建。新增 `test_stale_cache_without_reader_version_is_invalid` 锁定。
5. **test_api 断言过期**：M1 起 `character_count` 含三容器（living 35078 + dead_unprunable 4781 + dead_prunable 4237 = 44096），
   旧断言 `35078` 同步为 `44096`（inspect 另加 `dead_character_count == 9018`）。
   —— 这些缺陷**都只因真实集成从未在本机/CI 跑过而潜伏**，M3 首次把 `test_api.py` 真实分支跑绿。
6. **二进制指纹缓存门禁（M3.2，本提交新增）**：`reader_version` 只含 Cargo 版本（"0.1.0"），
   无法区分**占位 token 表**与**真实 token 表**构建。若用占位表二进制（`cargo build` 不带
   `CK3_IRONMAN_TOKENS`）prepare 写出的缓存被真实表二进制复用，会**静默**拿到 25 字节空数据
   （`landed_titles` 容器"找不到"）。修复：`SessionManager` 在每次 prepare 成功后记录 reader
   二进制指纹（路径/尺寸/修改时间）到 `data/cache/reader-binary.json`；`_cache_valid` 要求
   指纹与当前二进制一致才可复用缓存——跨构建一律判无效重建，绝不静默降级。
   新增 `test_stale_cache_from_different_binary_is_invalid` 锁定。清理方式：`data/cache` 属
   gitignored 运行态，旧版本残留缓存自然失效重建，无需手工删除。

## 5. 验证（全绿）

| 项 | 结果 |
| --- | --- |
| Rust `fmt --all -- --check` | 0 |
| Rust `clippy --release -- -D warnings` | 0 |
| Rust `test --release` | **16 passed**（M2 12 + M3 titles 4：容器定位/等级推导、Format A+B 排序、name_source、容器缺失告警） |
| 契约 `save-schema` | **25 passed**（TitlePeriod/TitleTier 双端一致） |
| 后端 pytest（无真实存档） | **137 passed / 9 skipped**（真实集成无样本跳过，CI 友好） |
| 后端 pytest（真实存档 `SHIGUAN_TEST_SAVE`） | **147 passed / 0 skipped**（含 `test_character_titles`：教宗国现任 5371；`test_adapter_*`；二进制指纹门禁） |
| 前端 tsc | 0 错 |
| 前端 eslint | 0 错 0 警告 |
| 前端 vitest | **117 passed**（含 `CharacterCard.test.tsx` 5 项、`TitlesPanel.test.tsx` 3 项） |
| 前端 vite build | 437 模块成功 |

> CI：`.github/workflows/ci.yml` rust 作业新增 `cargo test --release`，M3 的 16 项 Rust 测试进入 CI。

## 6. 真实存档实测（`SHIGUAN_TEST_SAVE` = 本机 62MB 存档，1.19.0.6，真实 token 表）

- `titles.json`：**19003 条头衔**，tier 分布 empire 128 / kingdom 401 / duchy 1205 / county 4811 /
  barony 11297 / unknown 1161（`h_` 历史帝号按 empire 属推断）；含 history 的 **4010** 条；
  `container_not_found` 告警 0（容器完整）。
- 人物侧：44096 人中 **7423** 人有头衔记录，**5230** 名现任统治者（`ruler_ids()`）；
  主要头衔推断告警 `primary_title_inferred` **0** 例（无同级多头衔现任冲突）、
  头衔持有冲突 `title_holder_conflict` **18** 例（真实数据，索引与逐条提取一致）。
- 样本：多头衔统治者 **6441**（8 段：王国 `k_youji` 幽蓟 + 公国 `d_youzhou` 范阳 + 4 县级 + 2 男爵领，
  primary=王国，`isRuler=true`，0 告警）；已故拜占庭皇帝 **4918**（3 头衔 742.7.1→743.11.2，
  6 条 `title_gain`/`title_loss` 全部 `confirmed` 且各带 1 条 EvidenceRef，**0 事件缺证据**）；
  教宗国 **5371**（`k_papal_state` 教宗国，kingdom，现任，start 752.3.22）。
- 名字解析：真实 token 表 + 本地化表下输出中文（`幽蓟`/`教宗国`/`拜占庭帝国`）；
  未解析 head 回退 key 不伪造；Mod 头衔 `c_anshi22_ssm`（柳城史家族，county）如实入库无告警。

## 7. 边界与后续

- 头衔 `tier` 由 key 前缀推导；`h_`（历史帝号）按 empire 处理属最佳推断，不是存档直述。
- `de_facto_liege_id` 已抄入 titles.json，但未在 TitlePeriod 中暴露（契约无字段）；如需「封臣关系」后续加。
- 名字解析链在**真实 token 表 + 本地化表**下可输出中文头衔（实测 `教宗国`）；占位表下 name 为 key 不伪造。
- `title_gain`/`title_loss` 由真实 holder 变更生成（`confirmed`）；`succession` 事件（`inferred`）
  仅在档案含**推断 primaryTitle** 时生成——本存档实测 0 例，无编造。
- 后续 M4（关系特质记忆深化）/ M5（TimelineBuilder）/ M6（前端传记页）继续。
- 地图 / 家族树 / LLM 传记正文仍属范围外。
