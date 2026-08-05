# Phase 3C 人工验收基准（Acceptance）

> 面向「全局历史语义层与可信叙事收口」。验收分两层：
> **1) 16 类角色样本（脱敏合成数据）**——确定性断言身份/领土/官职/机构表述；
> **2) 真实存档双样本抽查**——分类分布 + 无 tier 爵位硬编码 + 不推断因果。
> 两层共享同一份规则与管线，人工验收与 CI 断言同源。

## 0. 验收命令

```bash
# 16 类样本（全部为脱敏合成 titles.json，不依赖真实存档）
python scripts/phase3c_acceptance.py

# 追加真实存档双样本（直接读 data/cache/<saveId>/<signature>/titles.json，不重新 melt）
python scripts/phase3c_acceptance.py data/cache/0c8b991210969450/83348322-1785816674637354500 data/cache/e0248dcd0ecd94b8/62197033-1785684513969991700
```

退出码 0 = 全部通过；1 = 有失败（逐条打印明细）。

CI 等价物：`packages/biography-engine/py/tests/test_phase3c_acceptance.py`
（16 项参数化 + 1 项数量校验，复用 `tests/phase3c_fixtures.py`）。

## 1. 16 类角色样本

样本由 `tests/phase3c_fixtures.py` 定义（合成 titles.json，绝不来自真实存档）。
每类断言：`expectedHeadlineIdentity` / `realmStatus` / `primaryRealmTitle` /
`personalOffices` / `realmInstitutions` / `forbiddenInterpretations`（身份表述中**不得出现**的词）。

| # | id | 角色类型 | realmStatus | headlineIdentity | 关键禁止词 |
|---|----|---------|-------------|------------------|-----------|
| 1 | independent_emperor | 独立皇帝（e_ 无封君） | independent_ruler | 中原的最高统治者 | 皇帝/陛下/男爵/伯爵/公爵/国王 |
| 2 | independent_king | 独立国王（k_ 无封君） | independent_ruler | 大理的最高统治者 | 国王 |
| 3 | super_empire_identity | 超帝国身份（h_*） | independent_ruler | 华夏的最高统治者 | 皇帝 |
| 4 | vassal_duke | 封臣公爵（d_ 有封君） | vassal_ruler | 幽蓟的领主 | 公爵 |
| 5 | vassal_count | 封臣伯爵（c_ 有封君） | vassal_ruler | 魏州的领主 | 伯爵 |
| 6 | vassal_baron | 封臣男爵（b_ 有封君） | vassal_ruler | 云门的领主 | 男爵 |
| 7 | independent_minor_lord | 独立小领主（c_ 无封君） | vassal_ruler¹ | 孤竹的领主 | 伯爵 |
| 8 | institution_official | 无地机构官员（e_minister_*） | landless_official | 政事堂任职 | 帝国/国王 |
| 9 | personal_office_holder | 个人官职（Mod 规则经签名激活） | landless_official | 尚书令任职 | 帝国 |
| 10 | religious_leader | 宗教领袖（k_papal_state） | religious_leader | 教宗国 | 国王/皇帝 |
| 11 | dynasty_identity_holder | 家族身份头衔（x_nf_*） | courtier | 廷臣 | 皇帝/最高统治者 |
| 12 | temporary_title_holder | 临时头衔（x_c_nomad_*） | courtier | 廷臣 | 皇帝/最高统治者 |
| 13 | former_ruler | 前统治者（仅历史任期） | former_ruler | 幽蓟的前统治者 | 的领主 |
| 14 | courtier | 廷臣（无领地/官职） | courtier | 廷臣 | 平民/皇帝 |
| 15 | unknown_identity | 身份未明（存档无头衔记录） | unknown | 身份未明 | 平民/廷臣 |
| 16 | multi_title_same_day_split | 同日大量头衔变更按语义类型拆分 | independent_ruler | 中原的最高统治者 | 继承/征服/册封 |

¹ 独立小领主：当前 `RealmStatus` 为单一枚举，无法区分「独立小领主」，诚实落到
`vassal_ruler`；headline 用「的领主」而非爵位词。属已记录限制，不做伪造。

### 1.1 案例 9 的 Mod 规则隔离

`e_taizai_shangshu`（尚书令）只有在该样本含 `e_taizai_` 标题结构签名时才被
Mod 规则判为 `personal_office`；**无签名的另一存档环境**中同 key 回落到
base-game `e_` 主权领地规则，绝不借光。断言在 `check_case` 的
`isolationExpectation` 中完成。

### 1.2 案例 16 的因果约束

950.1.1 帝国创建（history kind=created）→ 原因被证实为 `creation`；
952.8.16 同日获两郡（c_weizhou/c_guzhu，同语义）合并为一条 `territorial_gain`，
原因如实为 `unknown` 且带叙事约束「存档未记录获得途径，不得推断为继承、征服、
册封」；同日机构任职独立成条（`institution_transition`）。时间相近绝不推断因果。

## 2. 真实存档双样本抽查结果（2026-08 实测）

样本路径：`data/cache/<saveId>/<signature>/titles.json`（真实存档已脱敏缓存，不提交）。

| 指标 | 样本甲 0c8b99… | 样本乙 e0248d… |
|------|---------------|---------------|
| titles | 19,160 | 19,003 |
| 现任统治者 | 4,709 | 5,230 |
| sovereign_realm_title | 1,432 | 1,466 |
| territorial_realm_title | 2,681 | 2,936 |
| subordinate_territory | 13,719 | 13,430 |
| realm_institution（e_minister_*） | 9（全对） | 9（全对） |
| religious_office | 1（k_papal_state 教宗国） | 1 |
| dynasty_identity / temporary / special_mod | 286 / 1021 / 11 | 196 / 929 / 36 |
| 历史语义事件 | 4,376 | 2,915 |
| cause=unknown（带约束） | 3,207 / 3,207 | 2,164 / 2,164 |
| cause=creation | 269 | 226 |

抽查断言：① `e_minister_*` 全部为机构，不被 base `e_` 规则吞掉；
② 现任统治者 headline 无 tier 爵位硬编码词；③ 所有 cause=unknown 事件均带
「不得推断因果」叙事约束。

## 3. 关键规则回退点

- **展示名**：存档直书（name_source=save）→ 本地化表 → 原 key 回退（resolved=False），
  永不按 tier 映射「男爵/伯爵/公爵/国王/皇帝」。
- **因果**：history kind=created → creation（confirmed）；其余一律 unknown 并带约束。
- **同日拆分**：`HistoricalEventSemanticBuilder` 按 `(date, semanticType, direction)`
  分组，同日不同语义类型拆成多条；同语义多条合并为一条（relatedTitleIds 保留全部）。
- **Mod 隔离**：Mod 规则仅当 `mods` 标识子串匹配或 `title_signatures` 前缀出现在
  存档标题键时激活；两列表皆空的文件永不激活。

## 4. 已知限制

1. `RealmStatus` 单枚举无法表达「独立小领主」「有地而兼任摄政」等复合状态。
2. 宗教职务仅有稳定前缀的教宗/教廷类键（k_papal_state、d_papacy 等）被识别；
   `d_patriarchate_in_the_east` 等无稳定前缀者诚实保持为领地。
3. 君臣/姻亲等身份证据依赖记忆与 family_data 交叉核对，不在本基准覆盖。
