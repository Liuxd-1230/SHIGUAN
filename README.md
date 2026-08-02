# 史官 SHIGUAN

> **读取存档，重写一生。**

面向《十字军之王 III（Crusader Kings III）》玩家的 **AI 历史传记生成器**。
导入 CK3 存档、选定人物，程序读取其一生中的可靠数据，整理为结构化档案与时间线，
再调用大语言模型，写成具有历史感、但用现代白话文表达的人物列传。

**不是**普通存档查看器，也**不是** AI 随机故事生成器——它是"基于真实存档证据，为 CK3 人物立传的 AI 史官"。
任何传记内容都尽量来源于存档数据，绝不会把模型的想象伪装成既成事实。

---

## 愿景

让玩家感觉这个游戏人物真正活过一生：出生与死亡、家族与出身、婚姻与战争、囚禁与流亡、
朋友与宿敌、重大成败与身后处境——都来自存档证据，经由白话纪传体呈现。

## 产品定位

- ✅ 基于真实存档证据的人物立传工具
- ❌ 不是 CK3 存档查看器
- ❌ 不是 AI 随机故事生成器
- ❌ 不是单纯属性面板
- ❌ 不是只有视觉效果的静态网页

## 技术路线

| 层 | 技术 |
|---|---|
| 前端 | React · TypeScript · Vite · Tailwind CSS · Zustand · Framer Motion（仅必要过渡）· PWA |
| 后端 | Python 3.11+ · FastAPI · Pydantic · SQLite |
| 解析 | 自研 Python PDX 文本解析器（明文侧）＋ Rakaly CLI 适配器（二进制/铁人侧，缺失显式报错） |
| 模型 | 兼容 OpenAI `/v1/chat/completions` 的本地或远程服务（llama.cpp / LM Studio / Ollama / OpenAI） |

## 核心数据流程（分层管线）

```
解析原始存档 → 建立索引 → 标准人物档案 → 构建时间线 → 事件排序与压缩
            → 生成提纲 → 生成正文 → 事实校验（不通过则要求模型修正）
```

- 绝不把整个存档直接塞给模型。
- 每条时间线事件带 `confidence`：confirmed / inferred / uncertain。
- 推断不得写成确定事实；虚构对白、内心活动、战役细节一律禁止。

## 隐私与安全

- 存档默认只在本地处理。
- 远程模型需用户显式开启，且仅发送**压缩后的结构化档案**，不发送完整存档。
- 不提交真实存档或密钥；`.env` 已被忽略，`.env.example` 不含任何真实密钥。

## 目录结构

```
SHIGUAN/
├─ apps/web/        # 前端（Phase 1 建立）
├─ apps/server/     # 后端（Phase 2 建立）
├─ packages/
│  ├─ save-schema/  # ✅ 数据契约（TS + Python）
│  ├─ shared/       # 共享工具（后续）
│  └─ biography-engine/ # 传记引擎（Phase 3）
├─ fixtures/mock/   # Phase 1 用的可信 Mock 数据
├─ docs/            # 架构 / 存档格式 / 传记管线 / 路线图
├─ scripts/         # 构建与检查脚本（后续）
├─ .env.example
├─ README.md
└─ AGENTS.md
```

## 当前进度

**Phase 0.5（数据契约收口）已完成**：TS/Python 契约严格同步（Enum 约束、索引/档案分离、`EvidenceRef` 证据引用、`FixtureEnvelope` Mock 包裹、`eventIds` 非空校验），并通过 pytest（19 项）与 TS 严格类型检查。
**Phase 1A（前端工程骨架）已完成**：`apps/web` 已可离线运行（`npm install && npm run dev`），四页面壳 + Mock 数据 + Zustand 状态 + PWA 骨架，`tsc --strict` 与 `vite build` 均通过。
**Phase 1B（纵向流程与状态管理打磨）已完成**：索引/档案按需加载、`validateProfileEnvelope` 运行时契约校验（修复返回包裹而非档案本体的真实 bug）、基于 History API 的可靠路由（修复 popstate 不刷新 location 的真实 bug）、传记页时间线↔正文双向滚动同步、史料依据面板仅高亮当前事件告警、确定性解析状态机（pending→running→success/error，支持中止与失败注入）、边界场景覆盖、PWA 安全缓存重写（显式静态白名单，绝不缓存敏感数据）、Vitest 32 项测试通过。验证见 [roadmap.md](docs/roadmap.md)。
**Phase 1C（响应式 · 无障碍 · 视觉定稿 · PWA 收尾）已完成**：东方数字史馆设计语言定稿（paper/ink/cinnabar/gold/jade/indigo 通道化 Design Token + 系统字体回退，不下载不提交字体）、共享组件库（MuseumSurface / ScrollPanel / SealButton / InkDivider / PortraitFrame / EvidenceBadge / TimelineNode / PageHeading / EmptyState / AssetImage / icons）、四页面视觉改造、Framer Motion `MotionConfig reducedMotion="user"` 与 CSS 媒体查询双重 reduced-motion、加载竞态修复（按人物的 `profileRequestStateById` + `requestId` 新鲜度判定）、键盘可达性（skip-link / 路由切换焦点管理 / 44px 触控）、移动端单栏重排（正文置顶→时间线→史料）、`/design-lab` 视觉实验室（不进正式导航）、PWA 缓存策略抽离为可单测纯函数 `swCachePolicy.ts`、ESLint 8 链路（`npm run lint` / `lint:fix`）、新增 34 项测试（共 66 项全绿）。验证见 [roadmap.md](docs/roadmap.md)。
**Phase 1C.1（验收修复与视觉收口）已完成**：补齐 `BiographyPage` 测试（12 项，全量 Vitest **96 项**）、`swHandler.ts` 可测试离线导航 handler（13 项）；路由无障碍（title 随路由含人物名、切换人物焦点重入 main）；克制动效（墨线延伸 / 朱砂落印 / 时间线脉冲 / 章节 `whileInView` 淡入 / EvidencePanel 交叉淡入，reduced-motion 双重降级）；东方素材生成 WebP（PNG 合计约 6.49 MB → WebP 约 1.11 MB，CSS `image-set` 回退）并移出 4 张参考图至 `docs/design-reference/`；`ParsePage` 移除 eslint-disable 改 `useCallback` 并修 deps 警告（`npm run lint` 零错误零警告）；清理临时产物并补 `.gitignore`；建立 `docs/ASSET_AUDIT.md` 素材审计表；经用户授权推送到公开远端。验证见 [roadmap.md](docs/roadmap.md)。
详见 [`docs/roadmap.md`](docs/roadmap.md) 与 [`docs/architecture.md`](docs/architecture.md)。

后续 Phase：
- **Phase 2** 存档解析 MVP
- **Phase 3** AI 传记生成
- **Phase 4** 家族树 / 地点 / 导出 / PWA 完善

## 快速开始（Phase 1 起补充）

```bash
# 前端
cd apps/web && npm install && npm run dev

# 后端（Phase 2 起）
cd apps/server && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

## 许可证

本项目自有代码采用 MIT。第三方解析组件（Rakaly / jomini / ck3save）按其各自许可使用，
部署前请核实具体条款；铁人令牌表按 PDS 协议不随本项目分发。
