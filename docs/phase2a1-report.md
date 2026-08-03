# Phase 2A.1 验收报告 —— 真实路由分页 / CI / 安全导入

> 延续 Phase 2A 的真实解析管线，补齐三项验收缺口（任务 #104 / #106 / #107），
> 并完成后端/前端/契约全部测试与 GitHub Actions CI，随后提交。
> Push 受沙箱至 `github:443` 的网络写入限制（与上一轮一致），由用户本机执行。

## 1. 范围与硬约束

- 不接入 LLM、不生成传记正文、不实现地图/家族树（与 Phase 2A 一致）。
- 真实存档解析沿用 ck3-reader Rust sidecar（占位全量 token 表，melt 完整、未知 token=0）。
- 诚实原则：faith/dynasty 在占位 token 表下仍为数值 id，无头衔/领地地图，绝不伪造。

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

## 4. 验证结果（本地全绿）

| 检查项 | 命令 | 结果 |
| --- | --- | --- |
| 后端 pytest | `apps/server` pytest | **82 passed, 8 skipped**, 1 warning |
| 契约 pytest | `packages/save-schema/py` pytest | **19 passed** |
| 前端类型检查 | `npm run typecheck` | 通过（tsc --noEmit） |
| 前端 Lint | `npm run lint` | **0 错误 / 0 警告** |
| 前端测试 | `npm test` (vitest) | **104 passed**（新增 RealFlow 4 项） |
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
