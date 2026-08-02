# fixtures/mock —— Phase 1 前端原型用的可信 Mock 数据

本目录存放 **Mock（模拟）数据**，专门用于 Phase 1 的"可交互前端原型"。
这些数据的唯一用途是让前端在没有真实解析器的情况下，完整演示页面与交互。

## 硬规则

1. **明确标注非真实解析**：任何 Mock 文件必须在顶部注释 / 字段中声明
   `"isMock": true` 与 `"source": "fixtures/mock"`，绝不可伪装成真实存档解析结果。
2. **结构必须严格符合数据契约**：Mock 的字段与类型必须与
   `packages/save-schema/src/types.ts` 中的 `CharacterProfile` / `TimelineEvent` 等一致，
   以便 Phase 2 接入真实解析后前端无需改结构。
3. **覆盖三类证据**：至少包含 `confirmed` / `inferred` / `uncertain` 三种 `confidence` 的事件，
   用于演示"史料依据"面板与"不确定信息提示"。
4. **覆盖关键边界场景**（供前端测试与演示）：
   - 多次婚姻（`spouses` 多个 `RelationshipPeriod`）
   - 多个头衔（`titles` 多个 `TitlePeriod`，含 `isCurrent`）
   - 无头衔人物（空 `titles`）
   - 无法定位地点（`residences` 中 `confidence: "inferred"`，或 `uncertain` 地点）
   - 日期缺失（`birthDate` / `deathDate` 部分为空）
   - 推断事件（如"可能居住于首府"）标记为 `inferred`

## 建议文件

- `arnulf.json`：一名封建公爵的完整 `CharacterProfile` + `timeline`（含三类证据、多次婚姻、多头衔）。
- `lowborn.json`：一名无头衔、出身低微、部分日期缺失的人物（用于演示边界与不确定提示）。
- `index.json`：人物选择页用的简要列表（`CharacterRef[]` 摘要）。

> 这些文件将在 Phase 1 由前端原型任务具体生成。本说明先行定义契约，避免 Phase 1 临时拍脑袋。

## 不要做的事

- 不要在这里放真实 CK3 存档（`.ck3`）或任何真实用户数据。
- 不要为了"好看"而编造与契约不符的字段。
- 不要把这些 Mock 当成解析器输出传给模型或写入数据库。
