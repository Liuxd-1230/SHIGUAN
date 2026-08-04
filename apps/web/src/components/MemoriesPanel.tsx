import { useMemo } from "react";
import type {
  CharacterProfile,
  CharacterRef,
  LifeEvent,
  RelationshipPeriod,
} from "@shiguan/save-schema";
import MuseumSurface from "./MuseumSurface";
import InkDivider from "./InkDivider";
import { cn } from "../lib/cn";

/** 关系语义标签（不伪造：isFormer/betrothed/concubine 均来自存档直述字段）。 */
function relationshipLabel(r: RelationshipPeriod): string {
  if (r.isFormer) return r.type === "concubine" ? "前妾室" : "前配偶";
  switch (r.type) {
    case "spouse":
      return "配偶";
    case "betrothed":
      return "婚约";
    case "concubine":
      return "妾室";
    default:
      return "关系";
  }
}

/** 记忆事件类型 → 中文短标签（未知类型如实显示 "事件"）。 */
function memoryTypeLabel(e: LifeEvent): string {
  switch (e.type) {
    case "marriage":
      return "婚姻";
    case "child_birth":
      return "子嗣出生";
    case "death":
      return "离世";
    case "war":
      return "战役/战争";
    case "title_gain":
      return "获封";
    case "title_loss":
      return "失封";
    case "succession":
      return "继承";
    default:
      return "事件";
  }
}

function memoryDate(e: LifeEvent): string {
  return e.date ?? "日期不详";
}

/** 人名芯片：名字 + 未解析提示，可点击溯源路径用 title 展示。 */
function NameChip({ name, id, unresolved, sourcePath }: { name: string; id: string; unresolved?: boolean; sourcePath?: string }) {
  return (
    <span
      title={sourcePath ?? `character/${id}`}
      className="inline-flex items-center gap-1 rounded-md border border-ink-400/40 bg-paper-100 px-2 py-0.5 text-xs text-ink-800"
    >
      {name}
      {unresolved && <span className="text-[10px] text-ink-400">（未解析）</span>}
    </span>
  );
}

function RefChip({ r }: { r: CharacterRef }) {
  return (
    <NameChip
      name={r.name}
      id={r.id}
      unresolved={r.name === r.id}
      sourcePath={r.sourcePath}
    />
  );
}

/** 关系分组：标题 + 计数 + 芯片列表（空组不渲染，避免空白噪音）。 */
function RelationGroup({ title, items, badge }: { title: string; items: CharacterRef[]; badge?: string }) {
  if (!items || items.length === 0) return null;
  return (
    <div>
      <h3 className="text-xs font-semibold tracking-wide text-ink-500">
        {title}
        <span className="ml-1.5 text-[10px] text-ink-400">({items.length})</span>
        {badge && <span className="ml-1.5 text-[10px] text-gold-700">{badge}</span>}
      </h3>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {items.map((r) => (
          <RefChip key={`${title}-${r.id}`} r={r} />
        ))}
      </div>
    </div>
  );
}

/** 关系与记忆面板（M4）：关系计数 chips + 按日期排序的记忆事件列表。 */
export default function MemoriesPanel({ profile }: { profile: CharacterProfile }) {
  const spouseGroups = useMemo(() => {
    const spouses = profile.spouses ?? [];
    // 现任配偶 / 婚约 / 妾室排前，前任（isFormer）排后，保持稳定顺序。
    const sorted = [...spouses].sort((a, b) => {
      const rank = (r: RelationshipPeriod) =>
        (r.isFormer ? 1 : 0) * 100 + (r.type === "spouse" ? 0 : r.type === "betrothed" ? 1 : 2);
      return rank(a) - rank(b);
    });
    return sorted;
  }, [profile.spouses]);

  const memories = useMemo(() => {
    const items = profile.memories ?? [];
    // 有日期按 CK3 数值日期升序（未知日期排最后），保持与时间线一致的方向。
    return [...items].sort((a, b) => {
      const ka = a.date ? a.date.split(".").map(Number) : [9999, 1, 1];
      const kb = b.date ? b.date.split(".").map(Number) : [9999, 1, 1];
      for (let i = 0; i < 3; i++) {
        if ((ka[i] ?? 0) !== (kb[i] ?? 0)) return (ka[i] ?? 0) - (kb[i] ?? 0);
      }
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    });
  }, [profile.memories]);

  const hasAny =
    spouseGroups.length > 0 ||
    (profile.siblings?.length ?? 0) > 0 ||
    (profile.relatives?.length ?? 0) > 0 ||
    profile.liege != null ||
    (profile.friends?.length ?? 0) > 0 ||
    (profile.rivals?.length ?? 0) > 0 ||
    (profile.lovers?.length ?? 0) > 0 ||
    memories.length > 0;

  if (!hasAny) {
    return (
      <MuseumSurface variant="raised" className="p-4">
        <h2 className="font-serif text-lg font-bold text-ink-900">关系与记忆</h2>
        <p className="mt-2 text-sm text-ink-500">
          存档的记忆库（character_memory_manager）与家庭关系记录中，未找到该人物的可解析条目。
        </p>
      </MuseumSurface>
    );
  }

  return (
    <MuseumSurface variant="raised" className="p-4">
      <h2 className="font-serif text-lg font-bold text-ink-900">关系与记忆</h2>
      <p className="mt-1 text-xs text-ink-500">
        关系由存档 family_data 与记忆库（became_* 成对推断标“推断”）整理；记忆为存档原始条目。
      </p>

      {(spouseGroups.length > 0 ||
        (profile.siblings?.length ?? 0) > 0 ||
        (profile.relatives?.length ?? 0) > 0 ||
        profile.liege != null ||
        (profile.friends?.length ?? 0) > 0 ||
        (profile.rivals?.length ?? 0) > 0 ||
        (profile.lovers?.length ?? 0) > 0) && (
        <div className="mt-3 space-y-3">
          {spouseGroups.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold tracking-wide text-ink-500">
                配偶与婚约
                <span className="ml-1.5 text-[10px] text-ink-400">({spouseGroups.length})</span>
              </h3>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {spouseGroups.map((r) => (
                  <span
                    key={`sp-${r.characterId}-${r.type}-${r.isFormer ?? false}`}
                    title={r.sourcePath ?? `character/${profile.id}/spouse/${r.characterId}`}
                    className={cn(
                      "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs",
                      r.isFormer
                        ? "border-ink-400/40 bg-paper-100 text-ink-600"
                        : "border-gold-500/50 bg-gold-500/5 text-ink-900",
                    )}
                  >
                    {r.name}
                    {r.name === r.characterId && (
                      <span className="text-[10px] text-ink-400">（未解析）</span>
                    )}
                    <span
                      className={cn(
                        "text-[10px]",
                        r.isFormer ? "text-ink-400" : "text-gold-700",
                      )}
                    >
                      {relationshipLabel(r)}
                    </span>
                  </span>
                ))}
              </div>
            </div>
          )}
          <RelationGroup title="兄弟姐妹" items={profile.siblings ?? []} />
          {profile.liege && (
            <div>
              <h3 className="text-xs font-semibold tracking-wide text-ink-500">
                君主
                <span className="ml-1.5 text-[10px] text-ink-400">(存于死亡记录)</span>
              </h3>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                <RefChip key={`liege-${profile.liege.id}`} r={profile.liege} />
              </div>
            </div>
          )}
          <RelationGroup title="亲属与姻亲" items={profile.relatives ?? []} badge="推断" />
          <RelationGroup title="好友" items={profile.friends ?? []} badge="推断" />
          <RelationGroup title="宿敌" items={profile.rivals ?? []} badge="推断" />
          <RelationGroup title="恋人" items={profile.lovers ?? []} badge="推断" />
        </div>
      )}

      {memories.length > 0 && (
        <div className="mt-4">
          <InkDivider className="my-3" />
          <h3 className="text-xs font-semibold tracking-wide text-ink-500">
            记忆
            <span className="ml-1.5 text-[10px] text-ink-400">({memories.length})</span>
          </h3>
          <ul className="mt-2 space-y-2">
            {memories.map((m) => (
              <li
                key={m.id}
                className="rounded-lg border border-ink-400/30 bg-paper-100 px-3 py-2"
              >
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <span className="text-xs font-semibold text-cinnabar-700">
                    {memoryDate(m)}
                  </span>
                  <span className="text-[11px] text-ink-500">{memoryTypeLabel(m)}</span>
                </div>
                <p className="mt-0.5 text-sm leading-relaxed text-ink-700">
                  {m.description}
                </p>
                {(m.relatedCharacters?.length ?? 0) > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {m.relatedCharacters?.map((r) => (
                      <RefChip key={`${m.id}-${r.id}`} r={r} />
                    ))}
                  </div>
                )}
                {m.sourcePath && (
                  <p className="mt-1 break-all text-[10px] text-ink-400">{m.sourcePath}</p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </MuseumSurface>
  );
}
