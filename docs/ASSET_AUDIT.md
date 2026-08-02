# 东方素材审计表（Phase 1C.1 · 六 / 九）

本表记录 `apps/web/public/assets/oriental/` 下东方装饰素材的接入状态、引用位置与最终决定。
原则：**克制**——装饰素材不阻塞渲染、不进首屏关键路径、不提交真实存档/密钥；大图优先 WebP，PNG 回退。

## 一、随构建发布（public/assets/oriental/）

| 文件名 | 尺寸 | 模式 | 引用位置 | WebP | 压缩前→后 | 最终决定 |
| --- | --- | --- | --- | --- | --- | --- |
| `red-seal.png` | 1024×1024 | RGBA | `StartPage.tsx:51`、`ParsePage.tsx:224`（均引用 `.webp`） | ✅ 无损 922,554 B | 1,992,500 → 922,554 B（-53.7%） | **保留 PNG+WebP**；朱砂落印，至多两个正式场景（起始页 / 解析页），两处恰为上限。 |
| `paper-texture.png` | 1254×1254 | RGB | `index.css .paper-grain`、`DesignLabPage.tsx` | ✅ 有损 q82 72,528 B | 2,164,199 → 72,528 B（-96.6%） | **保留 PNG+WebP**；极淡宣纸纹理，低透明度（由调用处控制），CSS 走 `image-set` 优先 WebP。 |
| `oriental-hero-bg.png` | 1672×941 | RGB | `index.css .hero-mountain`（仅起始页） | ✅ 有损 q82 112,134 B | 2,333,644 → 112,134 B（-95.2%） | **保留 PNG+WebP**；仅起始页山水/舆图背景，CSS `image-set` 优先 WebP。 |
| `README.md` | — | — | — | — | — | 素材说明文档，随仓库发布。 |

> WebP 通过 CSS `image-set(...)` 与 `<img src="*.webp">` 引用；`AssetImage` 在加载失败时 `onError` 返回 `null`，整节点消失、绝不阻塞。`red-seal.webp` 在无 WebP 支持的极旧环境下会退回「无印」状态（起始页/解析页仍可正常使用）。

## 二、移出构建（docs/design-reference/，仅参考图，不进仓库）

以下素材已移出 `public/`，**不进入 `dist` 构建产物**，仅作为设计参考与裁切源，且已被 `.gitignore` 排除，不随代码提交。

| 文件名 | 尺寸 | 模式 | 是否引用 | 用途 | 最终决定 |
| --- | --- | --- | --- | --- | --- |
| `ref_full_total.png` | 1672×941 | RGB | 否 | 完整合成参考图 | **移出 public**；仅本地参考，不入构建、不入仓库。 |
| `evidence-icons.png` | 1536×1024 | RGBA | 否 | 证据类型图标表 | **暂不使用**；若后续需要证据图标，从此表裁切单个图标（建议 SVG/PNG 单独导出），不整体引用。 |
| `oriental-dividers.png` | 1536×1024 | RGBA | 否 | 分隔纹样表 | **暂不使用**；如需要装饰分隔线，提取 1–2 条矢量/透明化 PNG，不整体引用。 |
| `oriental-ornament-pack.png` | 1536×1024 | RGBA | 否 | 纹饰套装表 | **暂不使用**；仅提取实际所需单件，避免整包进首屏。 |

## 三、结论

- 实际进入首屏/构建的装饰大图仅 3 张，均已生成 WebP，总体积由约 **6.49 MB（PNG）降至约 1.11 MB（WebP）**，其中两张背景图降幅 >95%。
- 未使用素材（4 张参考图，约 9 MB）已全部移出 `public/`，不进 `dist`、不进 `git`。
- 死引用 `__not_exist__.png`（原 `DesignLabPage.tsx`）已移除，不再产生 404；Design Lab 的「优雅降级」说明保留，降级演示由 `hero-mountain` 的 CSS 回退呈现。
- `red-seal` 正式场景严格控制在两个（起始页 / 解析页），符合「至多两个正式场景」约束。
