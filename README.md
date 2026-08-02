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

**Phase 0（研究与架构）已完成**：数据契约、四份文档、配置基线、Mock 数据契约已落地。
详见 [`docs/roadmap.md`](docs/roadmap.md) 与 [`docs/architecture.md`](docs/architecture.md)。

后续 Phase：
- **Phase 1** 可交互前端原型（Mock 数据）
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
