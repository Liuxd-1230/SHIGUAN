import type { CharacterIdentity, EntityRef } from "@shiguan/save-schema";
import MuseumSurface from "./MuseumSurface";
import InkDivider from "./InkDivider";
import { cn } from "../lib/cn";
import {
  CONFIDENCE_LABELS,
  realmStatusLabel,
} from "../lib/labels";

/** 区块标题：3C.5 分区展示统一排版（分区块的 <h2>，供测试按 heading 定位）。 */
export function SectionHeading({
  title,
  hint,
  className,
}: {
  title: string;
  hint?: string;
  className?: string;
}) {
  return (
    <div className={cn("mb-3", className)}>
      <h2 className="font-serif text-lg font-bold text-ink-900">{title}</h2>
      {hint && <p className="mt-1 text-xs text-ink-500">{hint}</p>}
    </div>
  );
}

/** 主要身份（3C.2）：headline / realmStatus / primaryRealmTitle / 次要身份。 */
export function IdentitySection({ identity }: { identity?: CharacterIdentity }) {
  if (!identity || !identity.headlineIdentity) return null;
  const realm = realmStatusLabel(identity.realmStatus);
  return (
    <MuseumSurface variant="raised" className="p-4">
      <SectionHeading
        title="主要身份"
        hint="由现任头衔结构确定性推导；无法判定时如实标注，不按头衔等级硬编码爵位。"
      />
      <p className="font-serif text-xl font-semibold text-cinnabar-800">
        {identity.headlineIdentity}
      </p>
      <div className="mt-2 flex flex-wrap gap-2 text-xs">
        {identity.isHegemony && (
          <span
            className="rounded border border-cinnabar-700/50 bg-cinnabar-700/10 px-2 py-0.5 font-medium text-cinnabar-800"
            title="该主头衔为霸权（h_* 超帝国）头衔，如唐（h_china）/ 罗马帝国（h_roman_empire）"
          >
            霸权
          </span>
        )}
        {realm && (
          <span className="rounded border border-gold-500/50 bg-gold-500/5 px-2 py-0.5 text-gold-800">
            {realm}
          </span>
        )}
        {identity.primaryRealmTitle && (
          <span className="rounded border border-ink-400/40 px-2 py-0.5 text-ink-600">
            主领地：{identity.primaryRealmTitle.name}
            {identity.primaryRealmTitle.resolved === false && "（未解析）"}
          </span>
        )}
        {identity.primaryOffice && (
          <span className="rounded border border-ink-400/40 px-2 py-0.5 text-ink-600">
            兼任官职：{identity.primaryOffice.name}
          </span>
        )}
        <span className="rounded border border-ink-400/40 px-2 py-0.5 text-ink-500">
          依据程度：{CONFIDENCE_LABELS[identity.confidence] ?? identity.confidence}
        </span>
      </div>
      {identity.secondaryIdentities && identity.secondaryIdentities.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm text-ink-700">
          {identity.secondaryIdentities.map((s) => (
            <li key={s}>· {s}</li>
          ))}
        </ul>
      )}
      {identity.warnings && identity.warnings.length > 0 && (
        <p className="mt-3 text-xs text-cinnabar-700">
          {identity.warnings.join("；")}
        </p>
      )}
    </MuseumSurface>
  );
}

/** 通用实体分区（领土/官职/机构/荣誉/宣称）；空列表不渲染。 */
export function EntityListSection({
  title,
  hint,
  items,
}: {
  title: string;
  hint?: string;
  items?: EntityRef[];
}) {
  if (!items || items.length === 0) return null;
  return (
    <MuseumSurface variant="raised" className="p-4">
      <SectionHeading title={title} hint={hint} />
      <ul className="mt-1 space-y-1.5">
        {items.map((e) => (
          <li
            key={e.id}
            className="flex flex-wrap items-baseline gap-x-2 rounded-lg border border-ink-400/40 bg-paper-100 px-3 py-2"
          >
            <span className="text-sm text-ink-900">{e.name}</span>
            {e.resolved === false && (
              <span className="text-[11px] text-ink-400">（未解析）</span>
            )}
            <span className="ml-auto text-[11px] text-ink-400">{e.id}</span>
          </li>
        ))}
      </ul>
    </MuseumSurface>
  );
}

/** 领土（3C.2）：主要领土（主权/领地王国及以上）与下属领地（伯/男爵领）。 */
export function TerritorySection({
  major,
  subordinate,
}: {
  major?: EntityRef[];
  subordinate?: EntityRef[];
}) {
  const hasMajor = !!major && major.length > 0;
  const hasSub = !!subordinate && subordinate.length > 0;
  if (!hasMajor && !hasSub) return null;
  return (
    <MuseumSurface variant="raised" className="p-4">
      <SectionHeading
        title="领土"
        hint="由 landed_titles 现任持有反解；主权/领地级与下属领地分别列出。"
      />
      {hasMajor && (
        <div className="mt-2">
          <h3 className="text-xs font-semibold tracking-wide text-ink-500">
            主要领土
          </h3>
          <ul className="mt-1 space-y-1.5">
            {major.map((e) => (
              <li
                key={e.id}
                className="flex flex-wrap items-baseline gap-x-2 rounded-lg border border-gold-500/50 bg-gold-500/5 px-3 py-2"
              >
                <span className="text-sm font-semibold text-ink-900">{e.name}</span>
                {e.resolved === false && (
                  <span className="text-[11px] text-ink-400">（未解析）</span>
                )}
                <span className="ml-auto text-[11px] text-ink-400">{e.id}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {hasSub && (
        <div className={cn("mt-2", hasMajor && "mt-4")}>
          <h3 className="text-xs font-semibold tracking-wide text-ink-500">
            下属领地
          </h3>
          <ul className="mt-1 space-y-1.5">
            {subordinate.map((e) => (
              <li
                key={e.id}
                className="flex flex-wrap items-baseline gap-x-2 rounded-lg border border-ink-400/40 bg-paper-100 px-3 py-2"
              >
                <span className="text-sm text-ink-900">{e.name}</span>
                {e.resolved === false && (
                  <span className="text-[11px] text-ink-400">（未解析）</span>
                )}
                <span className="ml-auto text-[11px] text-ink-400">{e.id}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </MuseumSurface>
  );
}

/** 数值化 CK3 日期（未零填充：944.10.22 vs 944.4.20，字符串排序会倒置）。 */
function dateKey(d?: string): number[] {
  if (!d) return [Infinity];
  return d.split(".").map((n) => {
    const v = Number(n);
    return Number.isFinite(v) ? v : 0;
  });
}

/** 历史语义事件（3C.3）：按语义类型拆分、带因果约束的"获得/失去"记录。 */
export function HistoricalEventsSection({
  events,
}: {
  events?: { eventId: string; summary: string; date?: string }[];
}) {
  if (!events || events.length === 0) return null;
  const sorted = [...events].sort((a, b) => {
    const ka = dateKey(a.date);
    const kb = dateKey(b.date);
    for (let i = 0; i < Math.max(ka.length, kb.length); i++) {
      const diff = (ka[i] ?? 0) - (kb[i] ?? 0);
      if (diff !== 0) return diff;
    }
    return a.eventId.localeCompare(b.eventId);
  });
  return (
    <MuseumSurface variant="raised" className="p-4">
      <SectionHeading
        title="统治历程"
        hint="同日多次头衔变更按语义类型拆分；获得原因除存档直书创建外一律如实标注未知。"
      />
      <div className="mt-1 space-y-2">
        {sorted.map((e) => (
          <div key={e.eventId} className="flex items-baseline gap-2">
            <span className="shrink-0 text-xs text-ink-500">{e.date ?? "日期不详"}</span>
            <InkDivider className="my-1 w-4 shrink-0" animateInk />
            <p className="text-sm leading-relaxed text-ink-700">{e.summary}</p>
          </div>
        ))}
      </div>
    </MuseumSurface>
  );
}
