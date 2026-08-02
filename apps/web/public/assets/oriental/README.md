# 东方数字史馆 · 装饰素材

本目录存放「东方数字史馆」视觉主题的**装饰性**素材。设计原则：

> **锦上添花，绝不阻塞。** 素材缺失、加载失败或被拦截时，页面必须优雅降级为
> 纸白底 / 内联 SVG，绝不白屏、绝不抛错、绝不影响核心流程。

## 已就位的素材

| 文件 | 尺寸 | 用途 |
| --- | --- | --- |
| `paper-texture.png` | 1254×1254 | 极淡宣纸纹理（CSS 工具类 `.paper-grain`） |
| `oriental-hero-bg.png` | 1672×941 | 起始页山水/舆图背景（CSS 工具类 `.hero-mountain`） |
| `red-seal.png` | 1024×1024 | 朱砂印章意象 |
| `oriental-dividers.png` | 1536×1024 | 分隔纹样拼图 |
| `evidence-icons.png` | 1536×1024 | 史料图标拼图 |
| `oriental-ornament-pack.png` | 1536×1024 | 云纹/缠枝等装饰拼图 |
| `ref_full_total.png` | 1672×941 | 参考底图 |

## 使用方式

- **背景纹理**：通过 `src/index.css` 的工具类引用（`url("/assets/oriental/...")`）。
  缺失时背景图静默失败，仅剩纸白底——安全。
- **装饰图**：统一走 `src/components/AssetImage.tsx`。该组件在 `onError` 时整节点
  消失（`return null`），且默认 `aria-hidden` + 空 `alt`，不干扰读屏。
- **状态/置信度表达**：一律用内联 SVG（`src/components/icons.tsx`）——不依赖任何
  位图，离线/缺图均可用，且天然支持 `currentColor` 与 reduced-motion。

## 无障碍与合规

- 所有装饰图 `aria-hidden`、空 `alt`。
- 不下载、不提交任何字体；系统字体回退（思源宋体 / PingFang SC 等）。
- 不提交真实 CK3 存档、密钥或 API Key。
- **绝不**用素材篡改人物的真实文化信息；`PortraitFrame` 仅展示调用方显式传入的
  名称 / 文化标签，不做任何文化改写或臆造。

## 新增素材

1. 将文件放入本目录（建议压缩、控制体积）。
2. 在 `src/index.css` 增加对应工具类，或用 `AssetImage` 引用。
3. 绝不要因此修改 `@shiguan/save-schema` 数据契约。
