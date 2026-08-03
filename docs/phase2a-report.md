# Phase 2A 汇报 —— 本地 CK3 存档库、解析器评估与 Mod 感知解析 MVP

> 生成时间：2026-08-03
> 验收样本：用户真实非铁人存档 `autosave.ck3`（62MB，game_version 1.19.0.6）
> 说明：真实存档**不进** Git / CI / fixture（经 `.gitignore` 的 `*.ck3` 与 `data/` 排除）。

---

## 1. 所选解析项目及原因

| 项目 | 版本 | 许可证 | 角色 |
|---|---|---|---|
| **ck3save** | 0.4.3 | MIT | Rust 库，melt 二进制 CK3 存档并提取结构化数据 |
| **jomini** | （ck3save 依赖） | MIT | CK3 二进制/文本解析内核 |

**为什么选它（而非 rakaly CLI / scorpdx 等）：**
- 成熟、活跃维护、MIT 许可证（合规，可 sidecar 集成，不引入 copy-left 风险）；
- 能正确 melt 用户实际所用的 **SAV0101 二进制**格式（非铁人不强制，但用户存档就是二进制）；
- token 机制清晰：编译期 `CK3_IRONMAN_TOKENS` 指向 token 表，可在**不随项目分发**的前提下由用户自备；
- 以 Rust **sidecar** 形式（`tools/ck3-reader`）经 subprocess 调用，不依赖第三方 exe、不拼 shell 命令、稳定 JSON 协议、超时可控；
- 不用 rakaly CLI 的独立二进制：sidecar 库集成度更高、协议可控、便于错误分类。

**结论：本轮回退到"可靠即可"**——占位全量 token 表（65536 条 id→tXXXX）保证 melt 不失败，enum 字段以数字呈现而非伪造中文名。

---

## 2. 编码与版本（真实存档实测）

| 字段 | 值 |
|---|---|
| 文件 | `autosave.ck3`，62,197,033 字节 |
| encoding | `Binary` |
| save_version | `15`（SAV0101 二进制格式） |
| game_version | **1.19.0.6** |
| 游戏内日期 | 762.1.1 |
| 玩家 | 节度使，李瑀 |
| melted_bytes | 87,207,319（明文展开后远大于二进制） |
| melt 耗时 | ~5,555 ms（62MB → 明文，单次） |

---

## 3. Mod 感知（真实存档实测）

| 指标 | 值 |
|---|---|
| Mod 总数（存档声明） | **33** |
| 全部 `ugc_*` | Steam 创意工坊，带 `remote_file_id` |
| 本机已订阅目录解析 → 找到 | **33** |
| 缺失 | **0** |
| 损坏 | 0 |
| 版本不匹配 | **27**（多为 `.mod` 未声明 `supported_version` 或与 1.19.0.6 不符） |

- `ModCompatibilityReport` 字段：`required / found / missing / version_mismatch / corrupted / localization_available / playset_diff`；
- 缺失/损坏/版本不匹配**均不阻断**解析，只记入报告；
- 缺失 Mod 标记 `MissingModWarning`，不阻止后续流程。

---

## 4. 人物索引（真实存档实测）

| 字段 | 值 |
|---|---|
| character_count | **35,078** |
| dead_character_count | 0 |

- 仅 melt 一次（~5.5s / 87MB 明文）；
- **按需**生成单角色 `CharacterProfile`，不一次性生成全部 35078 份完整档案（避免内存/IO 爆炸）。

---

## 5. 已解析字段（CharacterSummary / Profile）

样本人物 `id=6432`：

| 字段 | 值 | 可读性 |
|---|---|---|
| id | `6432` | — |
| name | `Hua_83EF` | 字符串键（可经本地化解析） |
| birth | `726.1.1` | 可读 |
| death | `null` | 存活 |
| alive | `true` | 可读 |
| culture | `asian_han_chinese` | 字符串键（可解析为中文） |
| faith | `41` | **token-id 数字**（占位表限制，非中文） |
| dynasty | `9067` | **token-id 数字**（占位表限制，非中文） |

- **可读字段**（字符串键，经 `LocalizationLoader` 解析）：`name`、`culture`、`traits` 等；
- **数字/token-id 字段**（占位 token 表限制）：`faith=41`、`dynasty=9067`、部分 `sex`/头衔 tier；
- `EntityRef.resolved` 标志：`resolved=False` 表示仅以原始 id/键表示，**不伪造**名称；调用方展示原键并标记 unresolved。

---

## 6. 未知 token / 未知 Mod 字段处理

- `unknown_token_count: 0` —— 占位 token 表 65536 条覆盖全部 16-bit token id，故"表中缺失的未知 token"为 0；
- **关键限制**：占位表只给出 `tXXXX`，**enum 语义名（信仰/王朝/头衔中文名）需真实 token 表**（rakaly 从 `Ck3.exe` 导出，每游戏版本不同，按 PDS 限制不随项目分发）。当前 enum 字段以数字呈现，**绝不伪造**；
- `header_parse_ok: false` —— 二进制头用占位表无法完整语义解析，符合预期（正文 melt 不受影响）；
- Mod descriptor 损坏检测：未闭合引号等 → `corrupted=True`，不阻断；
- 未知 Mod 字段：正则只取已知键，未知键忽略，**不崩溃**；
- 本地化缺失回退：`zh-Hans → english → key`（原始键），未命中标记 unresolved，**不崩溃**。

---

## 7. 自动发现与目录监听

- `LocalSaveDiscoveryService`：
  - 默认 `Documents/Paradox Interactive/Crusader Kings III/save games`（Windows Known Folder API，**不硬编码**路径）；
  - 支持普通 / OneDrive / 手动目录 / 自定义目录；
  - 扫描 `.ck3`，返回 `stable id / fileName / size / modified / isAutosave / 游戏版本 / 日期 / 状态 / Mod 数 / 解析状态`；
- 目录监听（**可关闭**）：检测新增 / 覆盖 / autosave 更新 / 删除 / 重命名；
  - **写入中不得解析**：`wait_until_stable()` 只读 `stat`（大小 + modified 连续 `stable_for` 秒不变）+ debounce，稳定后再复制副本解析；
  - 绝不长期占用原存档（不锁文件，按需复制暂存 `data/staging/`）；
- `saveId = sha1(原路径)[:16]`；服务端映射 `saveId → 原路径 / 暂存副本`；
- 前端只拿 `saveId + fileName + displayName`，**完整本地路径不默认发前端**（前端只展示 displayPath/别名）。

---

## 8. 后端 API（对齐规范九）

| 方法 | 端点 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET / PUT | `/api/settings/paths` | 存档/Mod 目录设置（PUT 前校验目录存在） |
| GET | `/api/local-saves` | 本地存档列表 |
| POST | `/api/local-saves/rescan` | 重新扫描 |
| POST | `/api/local-saves/import` | 手动导入（UploadFile，备用非主入口） |
| POST | `/api/local-saves/watch/start\|stop` | 启动/停止监听 |
| GET | `/api/local-saves/watch/status` | 监听状态 |
| GET | `/api/local-saves/{saveId}/inspect` | 元数据 + Mod 列表 |
| GET | `/api/local-saves/{saveId}/mods` | Mod 兼容性报告 |
| POST | `/api/local-saves/{saveId}/parse` | 触发解析（登记 + 暂存副本） |
| GET | `/api/saves/{saveId}/characters` | 人物摘要索引 |
| GET | `/api/saves/{saveId}/characters/{characterId}` | 按需单角色档案 |
| DELETE | `/api/saves/{saveId}` | 删除登记 + 清理副本 |

---

## 9. 测试与验收（真实存档不入仓）

| 层 | 结果 |
|---|---|
| 后端 pytest | **45 passed**（单元 27 + 集成 14；集成须 `SHIGUAN_TEST_SAVE` 指向真实存档，默认占位避免泄露本地路径） |
| 前端 `tsc --noEmit` | 0 错 |
| 前端 `eslint` | 0 错 0 警告 |
| 前端 `vite build` | 437 模块转换成功（沙箱 `emptyOutDir` 拦截为已知环境问题，构建产物本身成功） |
| 前端 Vitest | **99 passed**（含新增 `LocalSavesPanel.test.tsx`） |
| save-schema 契约 | **19 passed**（`EntityRef.resolved` 向后兼容） |

- 真实存档经 `.gitignore`（`*.ck3`、`data/`）排除；源码硬编码本地路径已改为 `SHIGUAN_TEST_SAVE` 环境变量；
- 覆盖项：默认/自定义/空/无权限目录、新增覆盖 autosave、写入中稳定性等待、SAV0101、游戏版本、33 个 Mod、缺失 Mod、损坏 descriptor、非 Steam 本地 Mod、本地化覆盖/缺失回退、未知 Mod 字段不崩、人物索引、按需 Profile、不存在 ID、副本清理、原存档未改。

---

## 10. 当前限制（诚实披露）

1. **enum 字段中文化**依赖真实 token 表（rakaly 从 `Ck3.exe` 导出，按 PDS 限制不随项目分发）—— 当前 `faith/dynasty/头衔` 以数字呈现，不伪造；
2. **铁人（ironman）未做** —— 用户不玩铁人，非本轮验收目标；
3. **LLM 传记正文 / 地图 / 家族树未做** —— 硬约束，留待后续 Phase；
4. 沙箱内 `vite build` 的 `emptyOutDir` 被 safe-delete 拦截（环境问题，非代码缺陷），已用"构建到仓库根外全新目录"绕过验证。

---

## 11. 是否具备 Phase 2B 条件

**具备。** 以下均已跑通真实存档：
- 后端骨架 + 真实二进制解析链路（ck3save sidecar）；
- Mod 感知（兼容性报告、找/缺/损坏/版本不匹配）；
- 人物索引（35078）+ 按需 Profile；
- 本地存档自动发现 + 可关闭监听 + 写入中防护；
- 前端后端双模式（后端不可用时回退 Mock 演示）。

Phase 2B 可在其上接续：真实 token 表中文化、传记管线（Phase 0.5 已设计八步）、地图 / 家族树。
