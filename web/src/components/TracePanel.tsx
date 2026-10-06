"use client";

import { useState } from "react";

import type { Trace } from "@/lib/api";
import { cn, ms } from "@/lib/format";
import { EyeOffIcon, LockIcon } from "./icons";
import { PrincipalChip } from "./PrincipalChip";

export function TracePanel({ trace, principals, compact = false }: { trace: Trace | null; principals: string[]; compact?: boolean }) {
  const [showAll, setShowAll] = useState(false);
  const total = trace ? trace.searchable_documents + (trace.excluded_documents ?? 0) : 0;
  const share = trace && total ? (trace.searchable_documents / total) * 100 : 0;
  return (
    <div className="space-y-4 text-sm">
      <section>
        <h3 className="text-[11px] font-semibold tracking-wide text-zinc-500 uppercase">Your principals</h3>
        <p className="mt-1 text-xs text-zinc-500">From your identity provider&apos;s groups claim, mapped by Clearance.</p>
        <div className="mt-2 flex flex-wrap gap-1">
          {(trace?.principals ?? principals).map((p) => (
            <PrincipalChip key={p} principal={p} />
          ))}
        </div>
      </section>

      {trace ? (
        <>
          <section>
            <h3 className="text-[11px] font-semibold tracking-wide text-zinc-500 uppercase">Searchable for you</h3>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-semibold text-zinc-900">{trace.searchable_documents}</span>
              <span className="text-zinc-500">documents</span>
              {trace.excluded_documents !== null && (
                <span className="ml-auto inline-flex items-center gap-1 text-xs text-zinc-500">
                  <LockIcon width={12} height={12} /> {trace.excluded_documents} not accessible
                </span>
              )}
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-zinc-200">
              <div className="h-full rounded-full bg-emerald-600" style={{ width: `${share}%` }} />
            </div>
            <p className="mt-2 text-xs text-zinc-500">
              Filtered before ranking, enforced again by PostgreSQL row-level security. The count of documents you
              can&apos;t access is the same for every question, so it never tells you whether one of them matched.
            </p>
            {!compact && (
              <>
                <button type="button" onClick={() => setShowAll((s) => !s)} className="mt-2 text-xs font-medium text-emerald-700 hover:underline">
                  {showAll ? "Hide" : "Show"} the documents you can search
                </button>
                {showAll && (
                  <ul className="mt-2 max-h-56 space-y-0.5 overflow-y-auto rounded-lg border border-zinc-100 bg-zinc-50 p-2 text-xs">
                    {trace.searchable.map((d) => (
                      <li key={d.id} className="truncate text-zinc-600">
                        <span className="text-zinc-400">{d.path ? `${d.path}/` : ""}</span>
                        {d.title}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </section>

          <section>
            <h3 className="text-[11px] font-semibold tracking-wide text-zinc-500 uppercase">Retrieved for this answer</h3>
            <ul className="mt-2 space-y-1.5">
              {trace.retrieved.map((item, index) => (
                <li
                  key={`${item.document_id}-${index}`}
                  className={cn(
                    "flex items-center gap-2 rounded-lg border px-2.5 py-1.5",
                    item.in_context ? "border-zinc-200 bg-white" : "border-dashed border-zinc-200 bg-zinc-50 text-zinc-400",
                  )}
                >
                  <span className="w-5 text-center text-xs font-semibold text-emerald-700">{item.number ?? "–"}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium text-zinc-800">{item.title}</span>
                    <span className="block truncate text-xs text-zinc-500">{item.section || "Introduction"}</span>
                  </span>
                  <span className="font-mono text-[11px] text-zinc-400">{item.score.toFixed(2)}</span>
                </li>
              ))}
              {trace.retrieved.length === 0 && (
                <li className="flex items-center gap-2 text-xs text-zinc-500">
                  <EyeOffIcon width={13} height={13} /> Nothing relevant among your documents.
                </li>
              )}
            </ul>
          </section>

          <section className="grid grid-cols-2 gap-2 text-xs">
            {Object.entries(trace.timings_ms).map(([key, value]) => (
              <div key={key} className="rounded-lg bg-zinc-50 px-2.5 py-1.5">
                <span className="block text-zinc-500 capitalize">{key}</span>
                <span className="font-mono text-zinc-800">{ms(value)}</span>
              </div>
            ))}
            <div className="col-span-2 rounded-lg bg-zinc-50 px-2.5 py-1.5">
              <span className="block text-zinc-500">Model</span>
              <span className="font-mono text-zinc-800">
                {trace.model}
                {trace.cache_hit ? " · cached for your principal set" : ""}
              </span>
            </div>
          </section>
        </>
      ) : (
        <p className="text-xs text-zinc-500">Ask a question to see what was searchable and what was retrieved.</p>
      )}
    </div>
  );
}
