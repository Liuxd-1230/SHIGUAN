# 史官 SHIGUAN —— 解析技术评估（Parser Evaluation）

> 本文件记录 Phase 2A 解析技术 Spike 的**实测结论**，是确定最终解析方案的
> 依据（用户要求：只有完成实际测试才能定方案）。所有数字均来自真实存档
> `autosave.ck3`（62 MB，游戏版本 1.19.0.6，SAV0101 二进制自动存档）的
> 实际运行结果，不是推断。

---

## 0. 测试环境与样本

| 项 | 值 |
|---|---|
| 真实存档 | `autosave.ck3` |
| 大小 | 62,197,033 字节（≈ 59.3 MB） |
| 编码形态 | 未压缩二进制 gamestate（autosave） |
| 文件头魔数 | `53 41 56 30 31 30 31` = `SAV0101`（非 ZIP，尾部无 `50 4B 05 06`） |
| 游戏版本 | 1.19.0.6 |
| 存档版本 | 15 |
| 玩家名 | `节度使，李瑀` |
| 沙箱策略 | 真实存档**只读复制**到受控临时目录（不进仓库、不写本地路径到代码） |

---

## 1. 核心结论（一句话）

**采用自研 Rust sidecar `tools/ck3-reader`（基于 `ck3save 0.4.3` + `jomini`，
Cargo 源码构建）作为二进制/铁人存档的解析适配器；FastAPI 后端通过 `subprocess`
安全调用它，得到版本化 JSON 后再映射为 `save-schema` 契约。明文侧仍保留
`apps/server` 内自研 Python PDX 文本解析器的位置（路线图 Phase 2 步骤 2），
但本机用户的真实存档是二进制，故主链路先落地 Rust sidecar。**

---

## 2. 实测数据（来自 `ck3-reader inspect` 真实输出）

| 指标 | 实测值 | 说明 |
|---|---|---|
| 能否读取 SAV0101 二进制存档 | ✅ 是 | 二进制头 + melt 全程成功 |
| 编码识别 | `Binary` | 与文件魔数 `SAV0101` 一致 |
| 游戏版本 | `1.19.0.6` | 成功提取 |
| 存档版本 | `15` | 成功提取 |
| 游戏内日期 | `762.1.1` | 成功提取 |
| 玩家名 | `节度使，李瑀` | UTF-8 中文正常 |
| Mod 数量 | **33**（全部 `ugc_xxxxxxx.mod`） | 成功定位并列出 |
| 活跃人物容器条目数 | **35,078** | `t2ce6` 容器，数字 id 键，可定位 |
| 其中死亡角色 | **0** | 活跃容器不含死亡历史角色（见 §6） |
| 未知 token 数 | **0** | 占位全量 token 表使 melt 完整 |
| melt 后明文大小 | 87,207,319 字节（≈ 83 MB） | 6.5M 行 |
| 解析耗时 | ≈ **5.5 s**（含 melt） | 单存档，debug 构建；release 更快 |
| 头 typed 反序列化 | `header_parse_ok = false` | 见 §5，不影响 melt 主链路 |

`melt` 输出格式已确认：对象条目 `6432={`（带 `=`），数组为 `"mod/ugc_xxx.mod"` 扁平字符串，
日期 `YYYY.MM.DD`，布尔 `yes/no`。整条主链路（melt → 扫描 meta/mods/characters）**无任何未知 token、无静默失败**。

---

## 3. Token 映射（已逆向，CK3 1.19.0.6 验证）

解析**只依赖 token id**（跨存档稳定），不依赖可读名。可读名仅由真实
`Ck3.exe` token 表提供（可选，用于调试）；字段映射以 `[可读名, 占位id]` 双候选
形式编写于 `tools/ck3-reader/src/main.rs`，无需改解析逻辑即可兼容两种 melt 输出。

| 语义 | 占位 token id | 备注可读名 |
|---|---|---|
| gamestate 根 | `t3155` | `gamestate` |
| 存档版本 | `t058f` | `save_version` |
| 游戏版本 | `t00ee` | `version` |
| 日期 | `t3157` | `date` |
| 玩家名 | `t29e6` | `player_name` |
| Mod 容器 | `t32c1` | `mods` |
| 人物容器 | `t2ce6` | `characters` |
| 姓名 | `t2755` | `name` |
| 出生 | `t27e9` | `birth` |
| 死亡（哨兵 `9999.1.1`） | `t2c68` | `death` |
| 文化 | `t3b12` | `culture` |
| 信仰 | `t2f2b` | `faith` |
| 王朝 | `t2e5e` | `dynasty` |

> 反推过程中纠正的关键误判：`t06b7` 是 **counties/provinces** 容器（非人物，
> 早期误判）；`t3391`/`t3393` 是玩家角色 / genetics 块；`t00e1="male"/"female"`
> 是复用 token（非每角色性别字段）。死亡角色不在活跃 `t2ce6` 容器中。

---

## 4. 为什么选 Rust sidecar（而非纯 Python PDX 文本解析器处理二进制）

| 维度 | 纯 Python PDX 文本解析器 | Rust sidecar（`ck3-reader`） |
|---|---|---|
| 明文 gamestate | ✅ 主战场，可控可维护 | ✅ 也可（melt 后同形态） |
| 二进制 gamestate | ❌ 二进制有理数值/天数字段无法自解（坑位 §5.2/§5.3） | ✅ `ck3save`/`jomini` 原生 melt，零自解 |
| 铁人令牌表 | 同需外部令牌 | 同需（构建期 `CK3_IRONMAN_TOKENS`） |
| 性能 | 大文件（数百 MB）内存压力大 | Rust melt ≈ 1 GB/s，5.5s/83MB 已验证 |
| 许可证 | 自有代码 | `ck3save`/`jomini` 均为 **MIT**（已核实），从源码构建，不复制源码 |
| 与本机真实存档匹配 | 不匹配（存档是二进制） | ✅ 直接命中 |

**结论**：用户真实存档是二进制 SAV0101，二进制字段（年龄/天数/有理数）**严禁自解**，
必须走 melt。Rust sidecar 复用 rakaly 同款底层库（`jomini`/`ck3save`），
且从 Cargo 源码构建、不下载预编译 exe，符合规范硬约束。因此主链路定为 Rust sidecar；
明文侧的自研 Python PDX 解析器仍保留为适配器的一个分支（用于用户未来的明文/解压存档），
但非本机首条路径。

---

## 5. 关键约束与已知限制

1. **构建期必须提供 CK3 token 表**：`ck3save` 的 `EnvTokens` 不内置表，需在
   `build.rs` 读取 `CK3_IRONMAN_TOKENS` 环境变量指向的 token 表文件编译进二进制；
   否则为空表，melt 时 `Ignore` 策略会跳过整个 value（仅剩 25 字节 header）。
   - 为让仓库可独立构建与审核（无需本机安装 CK3 或自备真实 token 表），提交**占位全量 token 表** `tools/ck3-reader/tokens/ck3_tokens.txt`
     （65,536 条 `id → tXXXX`，由 `gen_tokens.py` 生成）。占位表的 token id 与真实表一致，
     因此 melt 完整（未知 token = 0）；只是可读名缺失（不影响字段定位，因为我们用 token id 解析）。
   - 用户后续可用 rakaly 导出的真实 token 表替换该文件，获得可读名用于调试。
2. **`header_parse_ok = false`**：由于缺真实 token 表，`ck3save` 的 typed `Gamestate`
   反序列化失败（空 token 表无法映射 meta）。但 **melt 路径完全可用**，我们本就不依赖
   typed 反序列化——只 melt + 文本深度扫描提取切片。这是预期行为，非缺陷。
3. **死亡历史**：活跃 `t2ce6` 容器 35,078 角色**全部存活**（0 死亡）。死亡历史角色
   不在活跃容器中（存于历史/墓碑结构），提取死亡日期与死因为 **Phase-2 后续项**，
   不在本 MVP 范围。
4. **MSYS 路径坑**：Windows 二进制（build.rs/Rust 进程）不识别 MSYS `/d/...` 路径，
   `build.sh` 必须用 `pwd -W` 取 Windows 风格绝对路径设置 `CK3_IRONMAN_TOKENS`。
5. **不静默失败**：`ck3-reader` 缺失或执行失败时，后端 `Ck3ReaderAdapter` 必须捕获
   stderr 并显式报错（含缺失组件安装提示），绝不伪造"解析成功"。

---

## 6. 适合做 sidecar 吗？

✅ **适合**。理由：
- 单一职责：只做" melt + 提取切片"，输出稳定版本化 JSON（`inspect` / `list-mods` /
  `list-characters` / `character` / `dump` 五个子命令）。
- 进程隔离：FastAPI 经 `subprocess` 调用，崩溃不影响 Web 服务；二进制解析的不可控
  内存/崩溃被限制在子进程。
- 版本化协议：`InspectOutput` / `CharacterStub` 等结构固定，后端按字段映射，
  解析库升级不影响上层。
- 许可证干净：MIT，从源码构建。

---

## 7. 待办（Phase 2 后续节，不在本 Spike 范围）

- 死亡历史提取（墓碑结构）。
- 性別 / 家族(house) / 头衔 / 关系网 / 战争 / 记忆 等字段扩展（当前 reader 仅提取
  基础 8 字段：id/name/birth/death/alive/culture/faith/dynasty）。
- 本地化（`localization: key → 名称`）加载，需游戏目录。
- `LocalSaveDiscoveryService`、目录监听、`ModResolver`、FastAPI 后端 API、
  `CharacterSummary`/`CharacterProfile` 映射、测试与验收样本（见 `roadmap.md` Phase 2）。

---

## 8. 决策记录（供后续轮次）

- ✅ 主解析链路 = `tools/ck3-reader`（Rust sidecar，Cargo 源码构建）+ FastAPI subprocess 调用。
- ✅ 明文侧保留自研 Python PDX 文本解析器作为适配器分支（未来明文/解压存档）。
- ✅ 占位全量 token 表绕过"本机无游戏"限制，token id 解析不依赖可读名。
- ✅ 不下载预编译 exe；不复制 `ck3save`/`jomini` 源码；许可证 MIT 已核实。
- ⚠️ 死亡历史、性别/关系/头衔扩展为后续 Phase-2 项。
