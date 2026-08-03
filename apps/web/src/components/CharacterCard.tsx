import type { CharacterSummary } from "@shiguan/save-schema";
import { cn } from "../lib/cn";

function lifeSpan(birth?: string, death?: string, alive?: boolean): string {
  const b = birth ? birth.split(".")[0] : "生年不详";
  const d = death ? death.split(".")[0] : alive ? "在世" : "卒年不详";
  return `${b} – ${d}`;
}

/** 主头衔文案：未解析（resolved=false）时如实标出，不伪装成可读名。 */
function primaryTitleText(summary: CharacterSummary): string {
  const t = summary.primaryTitle;
  if (!t) return "无头衔";
  if (t.resolved === false) {
    return `${t.name}（未解析）`;
  }
  return t.name;
}

export default function CharacterCard({
  summary,
  onClick,
}: {
  summary: CharacterSummary;
  onClick: () => void;
}) {
  const title = primaryTitleText(summary);
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex min-h-[4.5rem] w-full flex-col gap-2 rounded-xl border border-ink-400/40 bg-paper-50 p-4 text-left transition-colors hover:border-cinnabar-700/50 hover:bg-paper-100"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate font-serif text-lg font-bold text-ink-950 group-hover:text-cinnabar-700">
            {summary.name}
          </h3>
          <p className="truncate text-sm text-ink-600">{title}</p>
        </div>
        <span className="shrink-0 text-xs text-ink-500">
          {lifeSpan(summary.birthDate, summary.deathDate, summary.isAlive)}
        </span>
      </div>

      <div className="flex flex-wrap gap-1.5 text-[11px]">
        {summary.dynasty && (
          <span className="rounded border border-ink-400/50 px-1.5 py-0.5 text-ink-500">
            {summary.dynasty.name}
          </span>
        )}
        {summary.isRuler && (
          <span className="rounded border border-gold-500/60 px-1.5 py-0.5 text-gold-700">
            统治者
          </span>
        )}
        {summary.isPlayerDynasty && (
          <span className="rounded border border-ink-400/50 px-1.5 py-0.5 text-ink-500">
            玩家王朝
          </span>
        )}
        {!summary.isAlive && (
          <span className="rounded border border-ink-400/50 px-1.5 py-0.5 text-ink-500">
            已故
          </span>
        )}
        {summary.evidenceWarningCount > 0 && (
          <span
            className={cn(
              "rounded border border-cinnabar-700/60 px-1.5 py-0.5 text-cinnabar-700",
            )}
          >
            证据告警 {summary.evidenceWarningCount}
          </span>
        )}
      </div>
    </button>
  );
}
