# fixtures/mock —— Phase 1 前端原型用的可信 Mock 数据

本目录存放 **Mock（模拟）数据**，专门用于 Phase 1 的"可交互前端原型"。
这些数据的唯一用途是让前端在没有真实解析器的情况下，完整演示页面与交互。

## 硬规则

1. **明确标注非真实解析（且用 FixtureEnvelope 包裹）**：任何 Mock 文件必须是一个
   `FixtureEnvelope<T>` 包裹结构，包含 `isMock: true`、`source: "fixtures/mock"`、
   `schemaVersion`、`generatedFor`、`data` 五个字段。真实业务模型（如 `CharacterProfile`）
   本身**不**携带这些 Mock 元数据，二者严格隔离，避免 Mock 数据污染业务契约。
   绝不可把 Mock 数据伪装成真实存档解析结果。
2. **结构必须严格符合数据契约**：`data` 内部的字段与类型必须与
   `packages/save-schema/src/types.ts` 一致（如 `CharacterProfile` / `TimelineEvent` /
   `CharacterSummary` / `EvidenceRef` / `ParsedSave` 等），以便 Phase 2 接入真实解析后
   前端无需改结构。`TimelineEvent` 的证据改用 `evidence: EvidenceRef[]` 而非仅 `sourcePath`。
3. **覆盖三类证据**：至少包含 `confirmed` / `inferred` / `uncertain` 三种 `confidence` 的事件，
   用于演示"史料依据"面板与"不确定信息提示"。
4. **覆盖关键边界场景**（供前端测试与演示）：
   - 多次婚姻（`spouses` 多个 `RelationshipPeriod`）
   - 多个头衔（`titles` 多个 `TitlePeriod`，含 `isCurrent`）
   - 无头衔人物（空 `titles`）
   - 无法定位地点（`residences` 中 `confidence: "inferred"`，或 `uncertain` 地点）
   - 日期缺失（`birthDate` / `deathDate` 部分为空）
   - 推断事件（如"可能居住于首府"）标记为 `inferred`，并至少有一条 `EvidenceRef` 记录推断依据

## 建议文件

- `arnulf.json`：`FixtureEnvelope<CharacterProfile>`——一名封建公爵的完整
  `CharacterProfile` + `timeline`（含三类证据、多次婚姻、多头衔，时间线事件带 `EvidenceRef`）。
- `lowborn.json`：`FixtureEnvelope<CharacterProfile>`——一名无头衔、出身低微、部分日期缺失的
  人物（用于演示边界与不确定提示）。
- `index.json`：`FixtureEnvelope<MockDataset>`——人物选择页用的索引包：
  `data.characterIndex` 为 `CharacterSummary[]` 摘要列表，`data.profiles` 为
  `Record<id, CharacterProfile>` 按需档案（可与上面两个文件的 `data` 对应）。

> 这些文件已由 Phase 1A 前端原型任务按本契约生成（`scripts/gen_mock.py` 复用 pydantic 契约产出 `arnulf/lowborn/index` 三份 + 拆分的 `profiles/<id>.json`）。本说明先行定义契约，避免 Phase 1A 临时拍脑袋。

## 前端如何消费（Phase 1B 起）

- `index.json`（`FixtureEnvelope<MockDataset>`）：其 `data.characterIndex`（`CharacterSummary[]`）直接喂给人物选择页做搜索/筛选/卡片摘要；`data.profileIds` 记录可懒加载的完整档案 id 列表。
- `profiles/<id>.json`（`FixtureEnvelope<CharacterProfile>`）：每个完整档案单独成文件，前端经 `import.meta.glob(eager:false)` 按需懒加载——进入某人物传记页才取对应 `profiles/<id>.json`，不一次性加载全部。
- 运行时校验：`characterRepository` 在载入每个包裹时调用 `validateProfileEnvelope`，强制校验 `isMock===true`、`source==="fixtures/mock"`、`schemaVersion`、字段类型与 `confidence∈{confirmed,inferred,uncertain}`，绝不依赖 TypeScript 类型断言来「保证」安全。

> 这些文件是 Phase 1 前端原型的数据契约，Phase 2 接入真实解析后将被真实 `ParsedSave` 取代，但结构保持一致。

## 不要做的事

- 不要在这里放真实 CK3 存档（`.ck3`）或任何真实用户数据。
- 不要为了"好看"而编造与契约不符的字段。
- 不要把这些 Mock 当成解析器输出传给模型或写入数据库。
