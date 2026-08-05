# Phase 3C.7：梁开 997.8.28 存档重新审计报告

存档：`data/staging/dd1f54e45acc4ed6.ck3`（TextZip，kind 2，CK3 1.19.0.6，存档日期 997.8.28，玩家「皇帝，梁开」）
方法：一次 `prepare --with-melted`，全部查询在同一 melt 目录内完成（`data/audit/liangkai-997/melt/`，已被 .gitignore 忽略，不分发）。
审计脚本：`scripts/audit_ck3_history_sources.py`（字段级取证）+ `scripts/audit_liangkai_997.py`（7 问答题取证）。

## 一、关键数字

| 项目 | 数值 |
| --- | --- |
| 人物总数（reader） | 85,941 |
| 头衔块数（reader） | 19,894 |
| title history 总条数 | **50,707**（reader 输出一致，0 丢失） |
| 显式 raw_type 总数 | **20,774** |
| 记忆总数（原始 / reader） | 177,773 / 177,773 |
| 战争总数 | 113 |
| cache schema 版本 | **4** |
| meta.player_id | **50366145**（梁开，非空） |

### 显式 raw_type 分布（20 类，含 18 类交接清单 + lease_revoked / usurped）

```
appointment_succession: 5849   migration: 2857   created: 2479
granted: 1939   conquest: 1645   destroyed: 1661   revoked: 1263
stepped_down: 1119   appointment: 736   conquest_populist: 330
abdication: 268   conquest_claim: 249   conquest_holy_war: 124
leased_out: 80   faction_demand: 61   swear_fealty: 51
independency: 35   lease_revoked: 12   usurped: 12   returned: 4
```

lease_revoked / usurped 不在 18 类清单内，`TitleHistoryActionNormalizer` 对未映射显式 type 一律保留 raw_type、标 unknown、加约束「不得推断为继承/征服/册封」——不猜测。

## 二、7 个问题

### Q1：梁开成为最高统治者时的 raw type

梁开当前持有 5 个 empire 级头衔，首持记录全部为**征服或创建**：

| 头衔 | 名 | 首持日期 | raw type |
| --- | --- | --- | --- |
| e_lingnan | 南中 | 990.7.26 | `conquest_claim` |
| e_liangyi | 梁益 | 994.4.19 | `conquest` |
| e_zhongyuan | 中原 | 996.12.24 | `conquest` |
| e_jingyang | 荆扬 | 996.12.24 | `conquest` |
| h_china | 唐 | 997.4.26 | `created`（kind=created） |

梁开于 997.4.26 **创建**了 h_china（唐）这一霸权帝号，成为最高统治者；此前各帝国领地均经征服取得。确定性摘要如实写「通过征服取得」/「存档记载该领地为该日创建」，不写具体战争名与对手（存档无 war→title 直接关联）。

### Q2：唐 / h_china / e_* 关系

- `h_china`（唐，id=14002）是**法理宗主**：`e_zhongyuan`（id=14003）、`e_liangyi`（id=15120）的 `de_jure_liege_id` 均指向 14002（数字引用，reader 已读）。
- `e_zhongyuan` 也是 `k_youji`（幽蓟）的法理宗主。
- 交接清单中的 `e_jinwang`、`e_liangnan` **不存在于本存档**（返回 None，SAVE_ABSENT）；实际帝国为 h_china（唐）/ e_zhongyuan（中原）/ e_liangyi（梁益）/ e_lingnan（南中）/ e_jingyang（荆扬）。
- de_jure_liege 全部为数字 title id，已由 `title_id → key` 反查表解析为 key。

### Q3：三省六部 title 的 raw type 分布

三省六部（9 个 `e_minister_*` 头衔：政事堂/御史台/枢密院/吏部/户部/礼部/兵部/刑部/工部）：

| raw type | 次数 |
| --- | --- |
| appointment_succession | 45 |
| appointment | 9 |
| created | 9 |
| destroyed | 1 |

结论：以 **appointment_succession** 为主（行政任命体系下继任，**不是**世袭继承）。确定性文案用中性制度化措辞「经任命继任」。

### Q4：同日大量 title 变化是否包含多种 cause

是。梁开同日多 title 变更共 2 个混合 cause 日：

- `993.7.26`：3 条变更，raw types = {created, revoked}。
- `997.4.26`：3 条变更，raw types = {created, revoked, stepped_down}。

典型样例（P0 修复的直接验证）：997.4.26 梁开同一天经两条**不同 raw type** 获得两个领地——

```
c_henan（河南）   @997.4.26 raw=revoked
c_yunzhou_2（筠州）@997.4.26 raw=stepped_down
```

旧（3C.3）按 (date, semanticType) 合并 → 1 条「获得以下领地：河南、筠州」且 cause 取组内第一个；新（3C.7）按 rawTypeGroup 拆分 → **2 条独立 territorial_gain**（河南 / 筠州），各自 cause=unknown（revoked/stepped_down 对获得者而言机制未载，不编造征服/授予），证据各绑自身 history 条目。同日机构（三省六部）还呈现 997.4.26 `created holder=梁开` 后紧跟 `appointment holder=臣属` 的双向记录，被如实拆成「归入其统治体系」+「不再属于其统治体系」两条（存档确有两笔记录）。

### Q5：修复前后梁开历史事件数量变化

- 新（3C.7 按 cause/rawTypeGroup 拆分）：**15** 条历史语义事件（时间线事件同源 15 条）。
- 旧（3C.3 按 (date, semanticType) 合并、cause 取组内第一个）：**13** 条。
- Δ = **+2**（993.7.26、997.4.26 的 mixed-cause 拆分）。

### Q6：修复前后确定性史料摘要变化

| 日期 | 旧摘要（3C.3 合并，cause=组内第一个） | 新摘要（3C.7 拆分） |
| --- | --- | --- |
| 990.7.26 | 「通过征服获得：大理、南中」（conquest_claim 与 conquest 混入一组） | 「通过征服获得：大理、南中」（同组均为 conquest*，可合并，raw_type 各自保留） |
| 993.7.26 | 「以下领地被创建：梁家族；获得以下领地：步日、大理」（合并） | 拆为 realm_created（created）+ territorial_gain（unknown，保留「不得推断」约束） |
| 997.4.26 | 河南、筠州合并为 1 条，cause 取第一个 | 拆为 2 条 territorial_gain（unknown）；三省六部归入/脱离统治体系如实分开 |

全部摘要均不再出现「击败某人并夺取」；appointment_succession 用「经任命继任」；realm_institution 用「以下机构归入其统治体系/不再属于其统治体系」+ 固定约束「该记录表示政权机构的归属或控制关系，不代表人物本人在该机构任职」。

### Q7：修复前后 AI Prompt 事实数量变化

- 新：压缩档案（CompressedProfile v3）`selectedEvents` = **15** 条（拆分后逐条带 cause/evidence）。
- 旧：13 条（同日 mixed cause 被合并，组内第二个 title 的原因信息在压缩输入中丢失）。
- 变化来源：P0 拆分让 LLM 输入逐条带独立 raw_type/evidence，而非「第一个 title 决定整组」。

## 三、P1 reader 字段在 997 存档的实测结果

| 字段 | reader 输出 | 后端消费 |
| --- | --- | --- |
| was_player | 梁开 `was_player=True`（playable_data） | PlayerHistoryMarker{wasPlayer:true, isCurrentPlayer:true}（meta.player_id=50366145 匹配） |
| landed_data.domain | 梁开 50 条 domain title ids | CharacterDomain：50 条全部反查 key 成功，`holderCrossCheck=consistent`，0 warning |
| capital | title 顶层标量（如 h_roman_empire capital=2407） | TitleStructure.capitalTitleId（数字→key 反查）+ sourcePath + capitalResolved |
| de_jure_liege | 标量数字 id（如 14002） | TitleStructure.deJureLiegeId（→ key） |
| de_jure_vassals | 数字 id 列表 | TitleStructure.deJureVassalIds（→ key 列表） |
| claims | 数字 id 列表（如 claim={ 21599 22216 … }） | TitleStructure.claimantIds（与人物实际持有分开） |
| history_government | 标量（如 celestial_government，2947 处均为标量形态） | TitleStructure.historyGovernment（保留，不生成复杂文案） |

## 四、SAVE_ABSENT / READER_DROPPED 现状

- **SAVE_ABSENT**（存档本身不保存，语义层必须推导且标注，不得伪造）：`title_liege`、`primary_title`、`held_titles`（人物块与头衔块均无）。
- **READER_DROPPED**（仍有价值但本轮未读）：`landless`（头衔块顶层 2112 处）、`government`（头衔块 2947 处 / 人物 landed_data 9896 处）、`court_data`（人物容器 34750 处）。
- 人物块 `capital=` 计数 3821 为 `realm_capital=` 子串误命中（政权中心真实位置在 title 顶层 capital，已读）。

## 五、cache schema 版本

v3 → **v4**（3C.7 P1）：reader 新增 `was_player` / `domain_titles`（人物）、`capital` / `de_jure_liege` / `de_jure_vassals` / `claim` / `history_government` / `title_id`（头衔）、meta.json 新增 `player_id`。Rust `CACHE_SCHEMA_VERSION` 与 Python `session_manager.CACHE_SCHEMA_VERSION` 同步为 `"4"`，旧缓存自动失效重建。
