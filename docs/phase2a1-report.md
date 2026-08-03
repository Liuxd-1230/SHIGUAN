# Phase 2A.1 验收报告 —— 真实路由分页 / CI / 安全导入

> 延续 Phase 2A 的真实解析管线，补齐三项验收缺口（任务 #104 / #106 / #107），
> 并完成后端/前端/契约全部测试与 GitHub Actions CI，随后提交。
> Push 受沙箱至 `github:443` 的网络写入限制（与上一轮一致），由用户本机执行。

## 1. 范围与硬约束

- 不接入 LLM、不生成传记正文、不实现地图/家族树（与 Phase 2A 一致）。
- 真实存档解析沿用 ck3-reader Rust sidecar（占位全量 token 表，melt 完整）。
- 诚实原则：faith/dynasty 在占位 token 表下仍为数值 id，无头衔/领地地图，绝不伪造。
- 关于 `unknown_token_count`：**`unknown_token_count=0` 仅表示占位表覆盖了全部 16-bit token id（无缺失 id），并不代表 token 已被解析为人类可读值，也不等同于"兼容/已中文化"**。在占位表下，faith/dynasty 仍是数字 id，primary_title 等依赖真实 token 的字段尚未填充。

## 2. 完成的任务

### #104 安全手动导入（代码 + 测试）
- 手动导入端点 `POST /api/local-saves/import` 仅接受 `.ck3`，经 `_safe_import_filename`
  净化文件名（剥离路径分隔符与非法字符），写入受控 staging 目录，绝不落到任意路径。
- 单元层覆盖 `_safe_import_filename` 的路径穿越防护；端到端由 `test_routing_api.py` 验证。

### #106 前端真实路由 + 分页
- 新增真实路由（URL 携带 `saveId`，可刷新/深链恢复）：
  - `/saves/:saveId/characters` —— 真实人物选择页
  - `/saves/:saveId/characters/:characterId` —— 真实人物传记页
- 真实选择页（`RealCharacterBrowser`）：
  - 首屏仅取一页（`PAGE_SIZE=48`），服务端分页（`offset`/`limit`）；
  - 搜索经 300ms 防抖并重置到第一页；
  - 切换查询/翻页时 `AbortController` 取消过期请求，避免陈旧响应污染。
- **Zustand 不再持有全量人物**：真实模式按需分页加载，仅缓存当前页（≤48）与按人物档案
  （`profileCache`，按需），彻底消除「一次性拉取 35078 条」的缺陷。
- 传记页真实模式：不依赖全量索引，进入即置 `backendMode` + 激活存档，按需取档；
  刷新/深链到真实人物 URL 可恢复。
- Mock 流程不变（`/characters`、`/characters/:id`），由路由 `saveId` 有无自动区分，原测试不受影响。
- `store.ensureIndex` 改为仅 Mock 模式（移除潜在的全量拉取分支）。

### #107 GitHub Actions CI
- `.github/workflows/ci.yml` 四作业：
  1. **contract**：Python 3.11 + pydantic + pytest，跑 `packages/save-schema/py/tests`（19 项）。
  2. **server**：Python 3.11 + FastAPI/uvicorn/httpx/pytest/python-multipart，跑 `apps/server` 测试
     （单元 + 集成；集成在无 `SHIGUAN_TEST_SAVE` 时自动跳过）。
  3. **rust**：Rust `fmt --check`、`clippy -D warnings`、`cargo build --release`（ck3-reader sidecar）。
  4. **web**：Node 22 + `npm ci` + `typecheck` + `eslint` + `vitest` + `vite build`。
- 真实存档集成测试经 `SHIGUAN_TEST_SAVE` 守卫，CI 无真实存档则自动跳过（设计如此）。

## 3. 配套修正
- `config.resolve_reader_binary` 跨平台：Windows 用 `ck3-reader.exe`，其它平台用无扩展名
  `ck3-reader`（便于 Linux CI / 本地 Linux 开发找到二进制）。
- ck3-reader 运行 `cargo fmt --all` 对齐 rustfmt（CI fmt 门禁前本地预校验通过）。

## 3.5 本轮追加（任务 #1–#8，多存档隔离 / Windows smoke / 生命周期 / 增量监听 / 脱敏 / 空文件）

> 接续上轮 #104/#106/#107 收尾后，按追加要求补齐以下八项（代码 + 测试），本地全绿后再提交。

### #1 人物缓存/请求/in-flight 键改为复合键
- 前端 `store` 中所有人物缓存（`profileCache`）、请求状态（`profileRequestStateById`）、
  in-flight Promise 与每键序号的键，统一为 `dataSource::saveId::characterId`。
- `dataSource ∈ {mock, real}`、`saveId`、人物 `id` 三维隔离：两个真实存档即便含相同
  characterId 也各自独立、绝不串档；真实档不会误用 Mock 档案。
- 同步更新 `BiographyPage`、`App`、`realRepository.loadProfile(id, saveId?)`、
  `characterRepository` 接口与全部相关测试。

### #2 双真实存档同 characterId 防串档测试
- 新增 `store.isolation.test.ts`：两个不同 `saveId` 的真实档加载同一 `characterId=6432`，
  断言缓存键独立、档案互不覆盖、且 `mockCharacterRepository` 从未被调用（真实档不误用 Mock）。
- 另覆盖"真实档与 Mock 档同 id 隔离在各自键下"的场景。

### #3 SHGetKnownFolderPath 正确 ctypes GUID + Windows smoke test
- `known_folder.py` 改用正确的 `ctypes` GUID 结构（`GUID` 由 3 个 ULONG + 8 个 BYTE 组成，
  非字符串 Buffer），`SHGetKnownFolderPath` 入参/出参类型正确（`REFKNOWNFOLDERID`、
  `DWORD`、`HANDLE`、`PWSTR*`、`CoTaskMemFree` 释放）。
- 新增仅 Windows 执行的真实 smoke test（`test_known_folder.py`）：实际调用
  `SHGetKnownFolderPath(FOLDERID_Documents)`，断言返回真实文档目录且以 `Documents` 结尾；
  非 Windows 跳过（不依赖真实用户目录、绝不写个人目录）。

### #4 FastAPI lifespan + 关闭后 watcher 停止/清理测试
- `main.py` 创建 `FastAPI(lifespan=lifespan)`（此前未传入）。
- 新增 `test_lifespan.py`：用 `TestClient` 触发 startup/shutdown，断言关闭后
  全局监听线程停止、临时文件/缓存资源被清理（无泄漏）。

### #5 watcher 增量 + 前端 lastEventId + 卸载不关监听
- 后端 `watch/status` 支持 `sinceEventId`，事件新增单调 `seq` 字段；前端轮询携带
  `sinceEventId` 游标，仅处理返回的新事件并更新本地游标，历史事件不重复处理。
- `LocalSavesPanel` 在组件卸载时**不再调用 `watch/stop`**（全局监听为后台服务，由应用退出统一回收）。
- 新增前端测试：首轮对齐游标后轮询带 `sinceEventId`、历史事件不重复处理、新事件触发一次刷新、
  卸载不发送 `watch/stop`。

### #6 Mod API 路径脱敏
- `mod_resolver.ResolvedMod.to_dict()` 新增 `full_paths` 开关：默认**不**发送完整绝对路径，
  仅输出相对/脱敏后的路径（`descriptor_path`/`content_path`/`archive_path`/`localization_paths`
  默认经 `redact_path` 脱敏，避免泄露真实用户目录）。显式 `?full_paths=true` 才回退原值。
- `mods_endpoint` 接受该 query 参数；新增 `test_resolved_mod.py` 断言默认脱敏、显式开启才返回原值。

### #7 空导入文件返回 400 empty_file 并清理半成品
- 导入端点流式写入后，若 `written == 0`（空文件），返回 `400 empty_file` 并
  `dest.unlink(missing_ok=True)` 删除半成品 staging 文件（不登记、不残留）。
- 头校验失败 / 超限 / 其他异常仍按原路径清理半成品。

### #8 等待并确认 GitHub Actions 四作业成功
- 推送后等待 CI 四个作业（contract / server / rust / web）实际成功（见提交后状态）。

## 4. 验证结果（本地全绿）

| 检查项 | 命令 | 结果 |
| --- | --- | --- |
| 后端 pytest | `apps/server` pytest | **90 passed, 8 skipped**, 1 warning |
| 契约 pytest | `packages/save-schema/py` pytest | **19 passed** |
| 前端类型检查 | `npm run typecheck` | 通过（tsc --noEmit） |
| 前端 Lint | `npm run lint` | **0 错误 / 0 警告** |
| 前端测试 | `npm test` (vitest) | **109 passed**（新增 RealFlow / 隔离 / 监听增量 / 竞态复合键 等） |
| 前端构建 | `vite build` | 437 模块转换成功 |
| Rust fmt | `cargo fmt --all -- --check` | 通过 |
| Rust clippy | `cargo clippy --release -- -D warnings` | 0 警告 |
| Rust build | `cargo build --release` | 成功 |

> 说明：后端 8 个 skipped 为真实存档集成测试，需本地 62MB 存档（`SHIGUAN_TEST_SAVE`），
> 无则跳过；该路径在本地以真实存档验证通过。`1 warning` 为 starlette/httpx 弃用提示，无害。

## 5. 提交
- 提交 `3d4ca9a`：Phase 2A.1 收尾（#104 / #106 / #107）+ 配套修正。
- 沙箱至 `github:443` 的网络写入被环境限制（Connection was reset，与上一轮一致），
  push 由用户本机执行：
  ```bash
  git push origin master
  ```

## 6. 已知限制（诚实披露）
- CI 不运行真实存档集成测试（需 62MB 本地存档，含隐私路径）；该路径在本地以
  `SHIGUAN_TEST_SAVE` 验证通过。
- 真实模式不伪造数据：faith/dynasty 在占位 token 表下为数值 id，无头衔/领地地图
  （与 Phase 2A 一致，待真实 token 表替换后可得中文）。
- **当前尚无 primary title**：占位 token 表下 `primary_title` 字段未被填充（真实头像/头衔/领地地图均不可用），
  传记页/选择页的"头衔"展示位置在真实模式下显式回退为"无头衔"，不编造。
