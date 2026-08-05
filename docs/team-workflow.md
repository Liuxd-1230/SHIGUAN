# 史官 SHIGUAN —— 团队协作与项目管理手册

> 面向项目团队成员（含后续轮次的自主开发 Agent）。
> 目标是让新成员**一条命令跑起来**、**知道自己该改哪里**、**知道怎么验收**。
> 上游工作约定见 `AGENTS.md`（面向开发 Agent 的硬性边界与每轮工作方式）。

---

## 1. 仓库与协作模式

| 项 | 约定 |
|---|---|
| 远端 | `https://github.com/Liuxd-1230/SHIGUAN`（分支 `master`，公开） |
| 分支 | 主开发直接推 `master`；**不建 PR**（除非用户明确要求） |
| 提交粒度 | 按 Phase 提交，信息含（Phase/要点），如 `feat(3B): ...`、`fix(3A.1): ...` |
| 推送 | `git push origin master`；本机网络异常时可 `git -c http.proxy= push origin master` |
| 破坏性操作 | 禁止 `git push --force` / `git reset --hard` / 改写远端历史 |

> 团队看板：建议在 GitHub 仓库 **Settings → Projects** 启用 Projects 看板，
> 按 `roadmap.md` 的 Phase 建列（已完成 / 进行中 / 待办），每轮工作对应一个卡片。

---

## 2. 成员上手（一次跑通）

前置：Git、Python 3.11+、Node 18+、Rust（可选，仅重编译 sidecar 时需要）。

```bash
# 1) 克隆
git clone https://github.com/Liuxd-1230/SHIGUAN.git
cd SHIGUAN

# 2) 后端依赖
cd apps/server
python -m venv .venv            # Windows: .venv\Scripts\activate
.venv/Scripts/pip install -r requirements.txt   # 或 pyproject/uv 依赖，以仓库为准
# 后端启动（默认 127.0.0.1:8000）
.venv/Scripts/python -m uvicorn app.main:app --port 8000 --host 127.0.0.1

# 3) 前端（另一个终端）
cd apps/web
npm install
npm run dev                     # http://localhost:5173
```

### 本地模型（Phase 3A/3B 需要）

任选一个 OpenAI 兼容服务并指向 `http://127.0.0.1:8080/v1`（默认）：
llama.cpp server / LM Studio / Ollama。`.env` 示例：

```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=http://127.0.0.1:8080/v1
LLM_MODEL=qwen2.5-7b-instruct        # 按你的模型名填
LLM_ALLOW_REMOTE=false               # 远程模型需显式置 true
```
模型**未运行**时后端会诚实返回 `provider_unreachable`，不会伪造成功。

### Rust sidecar（可选）

```bash
cd tools/ck3-reader
cargo test --release
bash build.sh                        # 依 CK3_IRONMAN_TOKENS 决定真实/占位 token 表
```

---

## 3. 每轮必跑测试基线

| 套件 | 命令 | 当前基线 |
|---|---|---|
| 契约（TS/Python 双端） | `pytest packages/save-schema/py/tests/` | **29 passed** |
| biography-engine | `cd packages/biography-engine/py && python -m pytest` | **117 passed** |
| 后端 | `cd apps/server && .venv/Scripts/python -m pytest` | **240 passed / 13 skipped** |
| Rust | `cd tools/ck3-reader && cargo test --release` | **24 passed** |
| 前端 | `cd apps/web && npm run lint && npx tsc --noEmit && npx vitest run && npm run build` | **165 passed** |

- 修改 Python 后：`py_compile` + 相关 pytest。
- 修改 TS/JS 后：`tsc --noEmit` + eslint + `vite build`。
- 测试失败必须修复或回滚，不留无法启动的状态。

---

## 4. 数据与密钥边界（团队红线）

| 内容 | 状态 |
|---|---|
| `data/`（真实存档、缓存、SQLite） | `.gitignore` 忽略，**不提交** |
| `.env` | 忽略；`.env.example` 只有占位，不含真实 Key |
| 真实铁人 token 表 | 用户自备（`RAKALY_IRONMAN_TOKENS_PATH`），**不随仓库分发** |
| 模型 API Key / 本地绝对路径 / Prompt 原文 | 一律不入库、不入 API 响应 |

真实存档验证脚本（本地运行，不提交）：`data/phase3a_real_verify.py`、
`data/phase3a1_real_verify.py`、`data/phase3b_smoke.py`。

---

## 5. 文档索引（团队知识库）

| 文档 | 内容 |
|---|---|
| `README.md` | 产品定位、技术路线、快速开始 |
| `AGENTS.md` | 面向开发 Agent 的硬性边界与每轮工作约定（**必读**） |
| `docs/roadmap.md` | Phase 路线图与逐轮完成状态（**看板依据**） |
| `docs/architecture.md` | 架构与数据契约（TS↔Python 同步规则） |
| `docs/biography-pipeline.md` | 八步传记管线说明 |
| `docs/save-format-notes.md` | CK3 存档格式与解析策略 |
| `docs/phase3b-report.md` | 最近一轮（3B）实现与验证报告 |
| `docs/phase2b-m5-report.md` 等 | 历史 Phase 报告 |

## 6. 当前状态速览（2026-08）

- ✅ 已完成：Phase 0.5 / 1A / 1B / 1C / 1C.1 / 2A / 2A.1 / 2B M1–M5 / M5.1 /
  3A / 3A.1 / **3B（正文逐章生成 + 确定性 FactChecker 20 规则 + 异步任务 + 持久化）**。
- ⏳ 待办：正文编辑/保存 UI、真实 token 中文化收尾（M3.2）、家族树/地点/导出（Phase 4）。
- 每轮工作顺序见 `AGENTS.md` 第 2 节：先读文档 → 说明问题 → 调查 → 实现 →
  测试 → 汇报（修改了什么 / 为什么 / 如何验证 / 当前限制 / 下一轮建议）。
