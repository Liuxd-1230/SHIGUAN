# 加载存档后端超时：故障复盘与修复（2026-08-05）

## 一、用户报告

「加载存档的时候后端超时」——在梁开 997 存档（`data/staging/dd1f54e45acc4ed6.ck3`，
30MB，85,941 人物）上复现为：`GET /api/local-saves/{id}/inspect` 等待 120s 后返回
`500 {"error":{"code":"reader_error","message":"ck3-reader 执行失败：执行超时（>120s）"}}`。

## 二、根因链（逐环节实测定位）

1. **磁盘缓存损坏**。`data/cache/dd1f54e45acc4ed6/<sig>/` 内 `manifest.json` 是
   08:01 的旧 **v2** 版（与当前 `CACHE_SCHEMA_VERSION=4` 不符）；`memories.json`
   是**截断半成品**（12MB→24MB 两次不同截断，正常完整产物 33MB）；
   `characters.ndjson` 仍是 08:01 旧文件。`_cache_valid()` 判缓存无效。
2. **每次请求都重新 melt**。缓存无效 → `_ensure_session` → `session_manager.prepare`
   → 完整 melt 30MB 存档（手动实测 37–53s）。
3. **melt 超时被杀**。`READER_TIMEOUT_SECONDS=120` 在慢环境（杀毒扫描/磁盘抖动/
   系统负载）下不够大存档的一次 melt。`subprocess.TimeoutExpired` → 统一 500。
4. **留下更脏的半成品 → 恶性循环**。melt 被杀时缓存文件已写一半（meta 新、
   ndjson 旧、memories 截断），下次请求缓存依旧无效 → 再次 melt → 再次超时。
   每次失败都让缓存目录更脏，且不产生任何有效缓存。

**为什么手动 melt 只 37s 而服务端 >120s**：手动（命令行）环境无杀毒实时扫描、
无 HTTP 服务并发；服务端进程在用户机真实负载下 melt 明显变慢。`120s` 是早期
小存档（5.5s 实测）时代定下的余量，对大存档 + 慢环境不成立。

## 三、修复内容

| 文件 | 改动 | 作用 |
| --- | --- | --- |
| `apps/server/app/config.py` | `READER_TIMEOUT_SECONDS` 默认 **120→300**（`SHIGUAN_READER_TIMEOUT` 可覆盖） | 大存档在慢环境留足余量 |
| `apps/server/app/services/session_manager.py` | `prepare()`：缓存无效时**先 `rmtree` 脏目录再 melt**；melt 异常时**移除半成品**后 re-raise | 自愈：不再向脏目录覆盖写、不留半成品 |
| `apps/server/tests/test_session_manager.py` | +3 测试（脏目录清理重建 / 失败移除半成品 / 失败后重试成功） | 锁定自愈行为 |
| `apps/web/src/pages/RealParsePage.tsx` | 提示「大型存档首次解析可能需要 1–3 分钟」 | 降低用户焦虑 |

## 四、验证（真实存档回归）

| 场景 | 修复前 | 修复后 |
| --- | --- | --- |
| 删缓存后首次 inspect（全新 melt） | 120s 超时 → 500 | **200 in 49.7s** |
| 第 2 次 inspect（缓存命中） | — | **200 in 0.03s** |
| parse 完整链路（inspect→mods→parse） | — | **200 in 137s**（玩家「皇帝，梁开」、85,941 人物） |
| 损坏缓存 + 重启服务端（自愈回归） | 每次请求重 melt 且超时 | **200 in 52.9s**，5 个缓存文件全 v4 重建 |
| 后端 pytest | — | 270 passed / 13 skipped（+3 自愈测试） |
| Rust / 契约 / biography-engine / 前端 | — | 31 / 45 / 220 passed；tsc + eslint + vitest 178 + vite build 全绿 |

## 五、经验与后续

- **缓存写盘应原子化**：Rust `prepare` 若先把各产物写到临时文件、全部成功后
  rename 到最终目录，可彻底避免半成品。当前 Python 侧自愈已兜底，Rust 侧原子写
  可作为后续优化（改动面较大，未在本轮实施）。
- **超时阈值应随存档规模自适应**：可用 `melted_bytes`/存档体积估计 melt 耗时上界，
  而非固定值。当前 300s 默认 + 环境变量覆盖已覆盖绝大多数场景。
- 服务端需重启以加载新超时与自愈逻辑（开发环境已停掉测试进程）。
