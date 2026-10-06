import { Fragment, type ReactNode } from "react";

import { cn } from "@/lib/format";

const CITATION = /\[(\d{1,2})\]/g;
const BOLD = /\*\*([^*]+)\*\*/g;

/** Paragraphs and bullet lists (a small Markdown subset) with [n] markers turned into citation chips. */
export function AnswerText({
  text,
  citations,
  active,
  onCitation,
}: {
  text: string;
  citations: number[];
  active?: number | null;
  onCitation?: (n: number) => void;
}) {
  const known = new Set(citations);
  const inline = (line: string, key: string): ReactNode[] => {
    const nodes: ReactNode[] = [];
    let last = 0;
    for (const match of line.matchAll(CITATION)) {
      nodes.push(...bold(line.slice(last, match.index), `${key}-t${last}`));
      const n = Number(match[1]);
      nodes.push(
        known.has(n) ? (
          <button
            key={`${key}-c${match.index}`}
            type="button"
            onClick={() => onCitation?.(n)}
            className={cn(
              "mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-md px-1 align-middle text-[11px] font-semibold transition",
              active === n ? "bg-emerald-700 text-white" : "bg-emerald-100 text-emerald-800 hover:bg-emerald-200",
            )}
          >
            {n}
          </button>
        ) : (
          <Fragment key={`${key}-c${match.index}`} />
        ),
      );
      last = (match.index ?? 0) + match[0].length;
    }
    nodes.push(...bold(line.slice(last), `${key}-t${last}`));
    return nodes;
  };

  const blocks = text.split(/\n{2,}/).filter((b) => b.trim());
  return (
    <div className="space-y-3 leading-relaxed text-zinc-800">
      {blocks.map((block, b) => {
        const lines = block.split("\n").filter((l) => l.trim());
        const isList = lines.every((l) => /^\s*([-*•]|\d+\.)\s+/.test(l));
        if (isList) {
          return (
            <ul key={b} className="list-disc space-y-1.5 pl-5 marker:text-zinc-400">
              {lines.map((l, i) => (
                <li key={i}>{inline(l.replace(/^\s*([-*•]|\d+\.)\s+/, ""), `${b}-${i}`)}</li>
              ))}
            </ul>
          );
        }
        return (
          <p key={b}>
            {lines.map((l, i) => (
              <Fragment key={i}>
                {i > 0 && <br />}
                {inline(l, `${b}-${i}`)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}

function bold(text: string, key: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(BOLD)) {
    nodes.push(text.slice(last, match.index));
    nodes.push(
      <strong key={`${key}-b${match.index}`} className="font-semibold text-zinc-900">
        {match[1]}
      </strong>,
    );
    last = (match.index ?? 0) + match[0].length;
  }
  nodes.push(text.slice(last));
  return nodes.filter((n) => n !== "");
}
