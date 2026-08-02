import type { ReactNode } from "react";
import type { TimelineEvent } from "@shiguan/save-schema";
import MuseumSurface from "../components/MuseumSurface";
import ScrollPanel from "../components/ScrollPanel";
import SealButton from "../components/SealButton";
import InkDivider from "../components/InkDivider";
import PortraitFrame from "../components/PortraitFrame";
import EvidenceBadge from "../components/EvidenceBadge";
import TimelineNode from "../components/TimelineNode";
import EmptyState from "../components/EmptyState";
import PageHeading from "../components/PageHeading";
import AssetImage from "../components/AssetImage";
import { cn } from "../lib/cn";

// —— 色板样例（直接读取 :root 中的 CSS 变量，作为单一事实来源）——
const COLOR_GROUPS: { name: string; vars: [string, string][] }[] = [
  {
    name: "宣纸 paper",
    vars: [
      ["paper-50", "--paper-50"],
      ["paper-100", "--paper-100"],
      ["paper-200", "--paper-200"],
    ],
  },
  {
    name: "墨色 ink",
    vars: [
      ["ink-950", "--ink-950"],
      ["ink-800", "--ink-800"],
      ["ink-600", "--ink-600"],
      ["ink-400", "--ink-400"],
    ],
  },
  {
    name: "朱砂 cinnabar",
    vars: [
      ["cinnabar-800", "--cinnabar-800"],
      ["cinnabar-700", "--cinnabar-700"],
      ["cinnabar-600", "--cinnabar-600"],
    ],
  },
  {
    name: "旧金 gold",
    vars: [
      ["gold-700", "--gold-700"],
      ["gold-500", "--gold-500"],
      ["gold-300", "--gold-300"],
    ],
  },
  {
    name: "玉色 jade",
    vars: [
      ["jade-700", "--jade-700"],
      ["jade-500", "--jade-500"],
    ],
  },
  {
    name: "靛青 indigo",
    vars: [
      ["indigo-700", "--indigo-700"],
      ["indigo-500", "--indigo-500"],
    ],
  },
];

const CONFIDENCE_SWATCHES: { label: string; value: "confirmed" | "inferred" | "uncertain" }[] = [
  { label: "确认 confirmed", value: "confirmed" },
  { label: "推断 inferred", value: "inferred" },
  { label: "存疑 uncertain", value: "uncertain" },
];

// 时间线节点样例（用真实结构，便于预览组件外观）。
const SAMPLE_EVENTS: TimelineEvent[] = [
  {
    id: "ev1",
    type: "birth",
    title: "诞生于宫廷",
    description: "样例事件：诞生",
    date: "1001.03.12",
    confidence: "confirmed",
    evidence: [
      { id: "v1", sourceType: "save_block", description: "存档人物块", confidence: "confirmed" },
    ],
  },
  {
    id: "ev2",
    type: "marriage",
    title: "缔结婚姻联盟",
    description: "样例事件：婚姻",
    date: "1024.06.01",
    confidence: "inferred",
    evidence: [
      { id: "v2", sourceType: "memory", description: "记忆片段", confidence: "inferred" },
    ],
  },
  {
    id: "ev3",
    type: "war",
    title: "卷入边境战争",
    description: "样例事件：战争",
    date: "1038.09.20",
    confidence: "uncertain",
    evidence: [
      { id: "v3", sourceType: "war", description: "战争记录", confidence: "uncertain" },
    ],
  },
];

function Swatch({ varName, label }: { varName: string; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <span
        className="h-8 w-8 shrink-0 rounded-md border border-ink-400/40"
        style={{ backgroundColor: `rgb(var(${varName}))` }}
        aria-hidden
      />
      <span className="text-[11px] leading-tight text-ink-600">
        <span className="block font-medium text-ink-900">{label}</span>
        <span className="font-mono">{varName}</span>
      </span>
    </div>
  );
}

function Section({
  title,
  children,
  id,
}: {
  title: string;
  children: ReactNode;
  id?: string;
}) {
  return (
    <section id={id} className="scroll-mt-6">
      <h2 className="mb-3 font-serif text-xl font-bold text-ink-900">{title}</h2>
      {children}
    </section>
  );
}

export default function DesignLabPage() {
  return (
    <div className="mx-auto max-w-5xl px-5 py-10">
      <PageHeading
        eyebrow="TEMPORARY · 不进入正式导航"
        title="东方数字史馆 · 设计实验室"
        level={1}
      />
      <p className="mt-2 max-w-2xl text-sm text-ink-600">
        本页用真实组件 + Mock 数据集中展示全部视觉元素、动效与无障碍表达。
        验收通过后，同一套 Design Tokens / 组件会应用到正式页面（不维护两套 CSS）。
      </p>

      <div className="mt-8 space-y-10">
        <Section title="色彩令牌（单一事实来源：src/index.css 的 :root 变量）">
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {COLOR_GROUPS.map((g) => (
              <MuseumSurface key={g.name} variant="inset" className="p-4">
                <p className="mb-2 text-xs font-medium text-ink-800">{g.name}</p>
                <div className="grid grid-cols-2 gap-2">
                  {g.vars.map(([label, v]) => (
                    <Swatch key={v} varName={v} label={label} />
                  ))}
                </div>
              </MuseumSurface>
            ))}
          </div>
          <MuseumSurface variant="inset" className="mt-4 p-4">
            <p className="mb-2 text-xs font-medium text-ink-800">
              证据置信度（图标 + 形状 + 文字，不靠颜色）
            </p>
            <div className="flex flex-wrap gap-3">
              {CONFIDENCE_SWATCHES.map((c) => (
                <EvidenceBadge key={c.value} value={c.value} />
              ))}
            </div>
          </MuseumSurface>
        </Section>

        <Section title="字体与排版">
          <MuseumSurface variant="raised" className="space-y-3 p-5">
            <p className="font-serif text-3xl font-bold text-ink-950">
              衬线标题 · 思源宋体回退
            </p>
            <p className="text-base text-ink-700">
              正文使用系统无衬线（PingFang SC / Microsoft YaHei 回退），不下载、不提交字体，也不从 CDN 加载。
            </p>
            <p className="text-sm text-ink-500">
              小字说明：用于辅助说明与元信息。
            </p>
          </MuseumSurface>
        </Section>

        <Section title="组件库">
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <MuseumSurface variant="raised" className="space-y-4 p-5">
              <p className="text-xs font-medium text-ink-800">MuseumSurface（raised / inset / flat）</p>
              <div className="flex flex-wrap gap-3">
                <MuseumSurface variant="raised" className="px-3 py-2 text-sm text-ink-800">raised</MuseumSurface>
                <MuseumSurface variant="inset" className="px-3 py-2 text-sm text-ink-800">inset</MuseumSurface>
                <MuseumSurface variant="flat" className="px-3 py-2 text-sm text-ink-800">flat</MuseumSurface>
              </div>
              <ScrollPanel className="text-sm text-ink-700">
                卷轴面板 ScrollPanel：双线边框，立传质感。
              </ScrollPanel>
              <div>
                <p className="mb-2 text-xs font-medium text-ink-800">SealButton（四态）</p>
                <div className="flex flex-wrap gap-3">
                  <SealButton variant="primary" seal>载入</SealButton>
                  <SealButton variant="secondary">次按钮</SealButton>
                  <SealButton variant="danger">危险</SealButton>
                  <SealButton variant="ghost">幽灵</SealButton>
                </div>
              </div>
              <div>
                <p className="mb-2 text-xs font-medium text-ink-800">InkDivider</p>
                <InkDivider variant="seal" />
                <InkDivider variant="dotted" className="my-3" />
                <InkDivider variant="line" />
              </div>
            </MuseumSurface>

            <MuseumSurface variant="raised" className="space-y-4 p-5">
              <p className="text-xs font-medium text-ink-800">PortraitFrame（保留真实文化，不臆造）</p>
              <div className="flex items-end gap-6">
                <PortraitFrame name="阿努尔夫" cultureLabel="巴伐利亚" size={72} />
                <PortraitFrame name="李清照" size={72} />
              </div>
              <p className="text-xs font-medium text-ink-800">TimelineNode（键盘可达 · aria-current）</p>
              <ol className="space-y-2 border-l border-ink-400/50 pl-1">
                {SAMPLE_EVENTS.map((ev, i) => (
                  <TimelineNode
                    key={ev.id}
                    event={ev}
                    active={i === 0}
                    inChapter={i === 1}
                    onSelect={() => {}}
                  />
                ))}
              </ol>
              <div>
                <p className="mb-2 text-xs font-medium text-ink-800">EmptyState</p>
                <EmptyState title="暂无内容" description="示例空状态占位" />
              </div>
            </MuseumSurface>
          </div>
        </Section>

        <Section title="动效（克制 · 尊重 reduced-motion）">
          <MuseumSurface variant="raised" className="flex items-center gap-4 p-5">
            <span className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-cinnabar-700 text-paper-50 animate-seal-stamp">
              印
            </span>
            <p className="text-sm text-ink-700">
              落印动画（seal-stamp）为全站唯一的“仪式性主动画”，每页至多一个。
              在系统开启「减弱动效」时，CSS 媒体查询会自动将其禁用（Framer 由 MotionConfig 统一处理）。
            </p>
          </MuseumSurface>
        </Section>

        <Section title="东方素材（优雅降级）">
          <MuseumSurface variant="raised" className="space-y-3 p-5">
            <p className="text-sm text-ink-700">
              装饰性素材缺失或加载失败时整节点消失，绝不阻塞渲染。以下区块在素材不可用时退化为纸白 / 内联 SVG。
            </p>
            <div
              className="hero-mountain relative h-28 rounded-xl border border-ink-400/40"
              aria-hidden
            >
              <span className="absolute bottom-2 right-3 text-[11px] text-ink-500">
                hero-mountain（缺失则纸白）
              </span>
            </div>
            <AssetImage
              src="/assets/oriental/paper-texture.webp"
              className="h-16 w-full rounded-md paper-grain"
              eager
            />
          </MuseumSurface>
        </Section>

        <Section title="无障碍要点">
          <MuseumSurface variant="inset" className={cn("space-y-1 p-4 text-sm text-ink-700")}>
            <p>· 跳转主内容链接（skip-link）；焦点可见（旧金描边）。</p>
            <p>· 语义标签 + 地标（header / main / nav / section / article）。</p>
            <p>· 状态不只靠颜色：置信度用「图标 + 形状 + 文字」。</p>
            <p>· 时间线按钮键盘可达，最小触控 44px；aria-current 标记当前项。</p>
            <p>· 加载/错误用 aria-live / role=alert 播报。</p>
          </MuseumSurface>
        </Section>
      </div>
    </div>
  );
}
