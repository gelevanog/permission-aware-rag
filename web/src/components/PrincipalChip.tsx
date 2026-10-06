import { principalLabel } from "@/lib/acl";
import { cn } from "@/lib/format";

export function PrincipalChip({
  principal,
  tone = "neutral",
  onRemove,
}: {
  principal: string;
  tone?: "neutral" | "allow" | "deny" | "section";
  onRemove?: () => void;
}) {
  const isUser = principal.startsWith("user:");
  return (
    <span
      title={principal}
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono text-[11px] leading-4",
        tone === "neutral" && "border-zinc-200 bg-zinc-50 text-zinc-700",
        tone === "allow" && "border-emerald-200 bg-emerald-50 text-emerald-800",
        tone === "deny" && "border-rose-200 bg-rose-50 text-rose-700",
        tone === "section" && "border-amber-200 bg-amber-50 text-amber-800",
      )}
    >
      <span className="opacity-60">{isUser ? "user" : "group"}:</span>
      {principalLabel(principal)}
      {onRemove && (
        <button type="button" onClick={onRemove} className="ml-0.5 opacity-60 hover:opacity-100" aria-label={`Remove ${principal}`}>
          ×
        </button>
      )}
    </span>
  );
}
