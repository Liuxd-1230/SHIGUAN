import type { Confidence } from "@shiguan/save-schema";
import { CONFIDENCE_LABELS } from "../lib/labels";

const STYLE: Record<Confidence, string> = {
  confirmed: "border-gold/70 text-gold",
  inferred: "border-bone-dim/60 text-bone-muted",
  uncertain: "border-wine-bright text-wine-bright",
};

export default function ConfidenceBadge({
  value,
  className = "",
}: {
  value: Confidence;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] leading-none ${STYLE[value]} ${className}`}
      title={`证据置信度：${CONFIDENCE_LABELS[value]}`}
    >
      {CONFIDENCE_LABELS[value]}
    </span>
  );
}
