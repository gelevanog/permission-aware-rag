"use client";

import { useState } from "react";

import type { Answer, Citation } from "@/lib/api";
import { cn } from "@/lib/format";
import { AnswerText } from "./AnswerText";
import { FileIcon, LockIcon, SpinnerIcon } from "./icons";

export type AnswerState =
  | { status: "searching" }
  | { status: "streaming"; text: string }
  | { status: "done"; answer: Answer }
  | { status: "error"; error: string };

export function AnswerView({ state, compact = false }: { state: AnswerState; compact?: boolean }) {
  const [active, setActive] = useState<number | null>(null);
  if (state.status === "searching") {
    return (
      <p className="flex items-center gap-2 text-sm text-zinc-500">
        <SpinnerIcon /> Searching the documents you can access…
      </p>
    );
  }
  if (state.status === "error") {
    return <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{state.error}</p>;
  }
  if (state.status === "streaming") {
    return (
      <div>
        {state.text ? <AnswerText text={state.text} citations={[]} /> : <p className="text-sm text-zinc-500">Writing…</p>}
        <span className="mt-1 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-emerald-600 align-middle" />
      </div>
    );
  }
  const { answer } = state;
  if (answer.outcome === "no_answer") {
    return (
      <div className="flex items-start gap-3 rounded-xl border border-zinc-200 bg-zinc-50 px-4 py-3">
        <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-zinc-200 text-zinc-600">
          <LockIcon width={15} height={15} />
        </span>
        <div>
          <p className="font-medium text-zinc-800">{answer.text}</p>
          <p className="mt-1 text-xs text-zinc-500">
            Same reply whether the answer is in a document you can't open or nowhere at all.
          </p>
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <AnswerText
        text={answer.text}
        citations={answer.citations.map((c) => c.number)}
        active={active}
        onCitation={(n) => setActive((current) => (current === n ? null : n))}
      />
      {answer.trace.fallback && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">{answer.trace.fallback}</p>
      )}
      {answer.citations.length > 0 && (
        <div className="space-y-2 pt-1">
          <p className="text-[11px] font-semibold tracking-wide text-zinc-500 uppercase">Sources</p>
          <div className={cn("grid gap-2", !compact && "sm:grid-cols-2")}>
            {answer.citations.map((citation) => (
              <SourceCard
                key={citation.number}
                citation={citation}
                expanded={active === citation.number}
                onToggle={() => setActive((current) => (current === citation.number ? null : citation.number))}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function SourceCard({ citation, expanded, onToggle }: { citation: Citation; expanded: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={cn(
        "w-full rounded-xl border bg-white p-3 text-left text-sm transition",
        expanded ? "border-emerald-300 ring-2 ring-emerald-100" : "border-zinc-200 hover:border-zinc-300",
      )}
    >
      <span className="flex items-start gap-2.5">
        <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md bg-emerald-100 text-[11px] font-semibold text-emerald-800">
          {citation.number}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5 font-medium text-zinc-800">
            <FileIcon className="shrink-0 text-zinc-400" width={14} height={14} />
            <span className="truncate">{citation.title}</span>
          </span>
          <span className="mt-0.5 block truncate text-xs text-zinc-500">
            {citation.path ? `${citation.path} / ` : ""}
            {citation.section || "Introduction"}
          </span>
          <span className={cn("mt-1.5 block text-zinc-600", expanded ? "whitespace-pre-line" : "line-clamp-2")}>
            {citation.snippet}
          </span>
        </span>
      </span>
    </button>
  );
}
