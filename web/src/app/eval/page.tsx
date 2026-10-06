"use client";

import { useEffect, useState, type ReactNode } from "react";

import { Header } from "@/components/Header";
import { api, type EvalResults, type LatencySummary } from "@/lib/api";
import { cn, ms, pct } from "@/lib/format";
import { useSession } from "@/lib/session";

const SYSTEM_LABELS: Record<string, string> = {
  clearance: "Clearance (pre-filter + RLS)",
  rls_only: "RLS alone (app filter removed)",
  postfilter: "Post-filter the top-k",
  unfiltered: "No permission filter",
};

export default function EvalPage() {
  const { user, tokenFor } = useSession();
  const [data, setData] = useState<EvalResults | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    tokenFor(user.email)
      .then((token) => api.evaluation(token))
      .then(setData)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, [user, tokenFor]);

  const leak = data?.leak;
  const quality = data?.quality;
  const acl = data?.acl_change;
  const latency = data?.latency as Record<string, LatencySummary | string | number> | null | undefined;

  return (
    <div className="min-h-screen">
      <Header showUser={false} />
      <main className="mx-auto max-w-[1400px] space-y-5 px-6 py-6">
        <div>
          <h1 className="text-lg font-semibold text-zinc-900">Evaluation</h1>
          <p className="text-sm text-zinc-500">
            Committed results from <code className="font-mono text-xs">results/*.json</code>
            {leak?.date ? `, run on ${leak.date}` : ""}. Questions, corpus and canaries are hand-written (see the README).
          </p>
        </div>
        {error && <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}

        {leak && (
          <Card
            title="Leak test"
            subtitle={`${leak.users} users × ${leak.questions} adversarial questions = ${leak.systems.clearance?.pairs ?? 0} pairs per system${leak.generator ? ` · answers by ${leak.generator}` : ""}`}
          >
            <Table
              head={["System", "Pairs with a restricted chunk in the model's context", "Restricted chunks", "Pairs with a hidden canary in context", "Pairs with a hidden canary in the answer"]}
              rows={Object.entries(leak.systems).map(([name, s]) => [
                <span key="n" className="font-medium">{SYSTEM_LABELS[name] ?? name}</span>,
                <Rate key="r" value={s.context_leak_rate} count={s.pairs_with_restricted_chunk_in_context} />,
                s.restricted_chunks_in_context,
                s.pairs_with_hidden_canary_in_context,
                s.pairs_with_hidden_canary_in_answer ?? "not generated",
              ])}
            />
          </Card>
        )}

        {leak?.postfilter_recall_study && (
          <Card
            title="Why filter before ranking: recall of post-filtering"
            subtitle="Authorized questions × every user who may read the gold document. Stress rows add N copies of every non-company-wide document (like old versions of board packs)."
          >
            <Table
              head={["Copies of restricted docs", "k", "Recall, Clearance", "Recall, post-filter", "Empty contexts (post-filter)", "Answers lost"]}
              rows={leak.postfilter_recall_study.map((r) => [
                r.restricted_copies === 0 ? "none (the corpus)" : `${r.restricted_copies} (+${r.documents_added} docs)`,
                r.k,
                pct(r.recall_clearance),
                <span key="p" className={cn((r.recall_postfilter ?? 1) < (r.recall_clearance ?? 0) && "font-semibold text-rose-700")}>
                  {pct(r.recall_postfilter)}
                </span>,
                r.empty_postfilter,
                r.answers_lost_by_postfilter,
              ])}
            />
          </Card>
        )}

        {quality && (
          <Card
            title="Answer quality on authorized questions"
            subtitle={`${quality.retrieval.questions} answerable questions · retrieval recall@k ${pct(quality.retrieval.recall_at_k)}, MRR ${quality.retrieval.mrr ?? "–"} · judge: ${quality.judge ?? "none"}`}
          >
            <Table
              head={["Generator", "Correct (judge)", "Faithful (judge)", "Key facts present", "False refusals", "Unanswerable declined", "Generation p50 / p95"]}
              rows={Object.entries(quality.generators).map(([label, g]) => [
                <span key="m" className="font-medium">
                  {label} <span className="font-mono text-xs text-zinc-500">{g.model}</span>
                </span>,
                `${pct(g.summary.correctness, 0)} (${g.summary.correct}/${g.summary.answerable})`,
                pct(g.summary.faithfulness, 0),
                pct(g.summary.expect_met, 0),
                g.summary.false_refusals,
                `${g.summary.unanswerable_declined}/${g.summary.unanswerable}`,
                `${ms(g.summary.generate_ms.p50)} / ${ms(g.summary.generate_ms.p95)}`,
              ])}
            />
          </Card>
        )}

        <div className="grid grid-cols-2 gap-5">
          {acl && (
            <Card title="Permission changes" subtitle="Revoke a user's access, ask again, restore">
              <Stats
                items={[
                  ["Revocations excluded on the next query", `${acl.revocations.excluded_on_next_query}/${acl.revocations.trials}`],
                  ["ACL update p50 / p95", `${ms(acl.revocations.acl_update_ms.p50)} / ${ms(acl.revocations.acl_update_ms.p95)}`],
                  ["Embeddings recomputed", String(acl.revocations.embeddings_computed)],
                  ["Deleted documents gone on next query", `${acl.deletions.gone_on_next_query}/${acl.deletions.trials}`],
                  ["Re-ingesting a document (with embedding)", ms(acl.deletions.reingest_with_embedding_ms.p50)],
                ]}
              />
            </Card>
          )}
          {latency && (
            <Card title="Latency on CPU" subtitle="p50 / p95 on this machine">
              <Stats
                items={Object.entries(latency)
                  .filter(([, v]) => typeof v === "object" && v !== null && "p50" in (v as object))
                  .map(([k, v]) => {
                    const s = v as LatencySummary;
                    return [k.replace(/_ms/g, "").replace(/_/g, " "), `${ms(s.p50)} / ${ms(s.p95)}`];
                  })}
              />
            </Card>
          )}
        </div>

        {data?.calls_summary && (
          <p className="text-xs text-zinc-500">
            Real cloud calls: {data.calls_summary.total_requests} (ledger in results/calls.jsonl) · every model id free:{" "}
            {String(data.calls_summary.all_model_ids_free)}
          </p>
        )}
        {!leak && !quality && !error && <p className="text-sm text-zinc-500">No results yet: run the evaluation (make eval).</p>}
      </main>
    </div>
  );
}

function Card({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-zinc-200 bg-white p-5">
      <h2 className="text-sm font-semibold text-zinc-900">{title}</h2>
      {subtitle && <p className="mt-0.5 text-xs text-zinc-500">{subtitle}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-zinc-200 text-xs text-zinc-500">
            {head.map((h) => (
              <th key={h} className="px-3 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-zinc-100 last:border-0">
              {row.map((cell, j) => (
                <td key={j} className="px-3 py-2.5 text-zinc-700">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Rate({ value, count }: { value: number | null; count: number }) {
  return (
    <span className={cn("font-semibold", count === 0 ? "text-emerald-700" : "text-rose-700")}>
      {count} ({pct(value)})
    </span>
  );
}

function Stats({ items }: { items: [string, string][] }) {
  return (
    <dl className="grid grid-cols-2 gap-2">
      {items.map(([label, value]) => (
        <div key={label} className="rounded-lg bg-zinc-50 px-3 py-2">
          <dt className="text-xs text-zinc-500 capitalize">{label}</dt>
          <dd className="font-mono text-sm text-zinc-900">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
