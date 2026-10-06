"use client";

import { useEffect, useMemo, useState } from "react";

import { Avatar } from "@/components/Avatar";
import { Header } from "@/components/Header";
import { LockIcon } from "@/components/icons";
import { api, ApiError, type AdminDocument, type AuditEntry } from "@/lib/api";
import { cn, ms } from "@/lib/format";
import { useSession } from "@/lib/session";

const EVENT_STYLE: Record<string, string> = {
  ask: "bg-zinc-100 text-zinc-700",
  acl_update: "bg-amber-100 text-amber-800",
  delete: "bg-rose-100 text-rose-700",
  ingest: "bg-sky-100 text-sky-800",
  sync: "bg-sky-100 text-sky-800",
};

export default function AuditPage() {
  const { user, users, setUser, tokenFor } = useSession();
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [documents, setDocuments] = useState<AdminDocument[]>([]);
  const [forbidden, setForbidden] = useState(false);

  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!user) return;
    tokenFor(user.email)
      .then((token) => Promise.all([api.audit(token), api.adminDocuments(token)]))
      .then(([log, docs]) => {
        setEntries(log);
        setDocuments(docs);
        setForbidden(false);
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 403) setForbidden(true);
      });
  }, [user, tokenFor, version]);

  const titles = useMemo(() => new Map(documents.map((d) => [d.id, d.title])), [documents]);
  const names = useMemo(() => new Map(users.map((u) => [`user:${u.email}`, u])), [users]);

  if (forbidden) {
    return (
      <div className="min-h-screen">
        <Header />
        <main className="mx-auto max-w-xl px-6 py-24 text-center">
          <LockIcon className="mx-auto text-zinc-400" width={28} height={28} />
          <h1 className="mt-3 text-lg font-semibold">The audit log is for administrators</h1>
          <button
            type="button"
            onClick={() => setUser("ian.brooks@fernhill.test")}
            className="mt-5 rounded-xl bg-emerald-700 px-4 py-2 text-sm font-medium text-white"
          >
            Switch to Ian Brooks (IT Administrator)
          </button>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <Header />
      <main className="mx-auto max-w-[1400px] px-6 py-6">
        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-lg font-semibold text-zinc-900">Audit log</h1>
            <p className="text-sm text-zinc-500">
              Who asked what (a keyed hash and a short masked preview, never the full question), which documents were
              retrieved, and how many of the nearest candidates permissions excluded. Excluded content is never logged.
            </p>
          </div>
          <button type="button" onClick={() => setVersion((v) => v + 1)} className="rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-sm hover:bg-zinc-50">
            Refresh
          </button>
        </div>
        <div className="mt-4 overflow-hidden rounded-2xl border border-zinc-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-zinc-200 bg-zinc-50 text-xs text-zinc-500">
                <th className="px-4 py-2.5 font-medium">Time (UTC)</th>
                <th className="px-4 py-2.5 font-medium">Who</th>
                <th className="px-4 py-2.5 font-medium">Event</th>
                <th className="px-4 py-2.5 font-medium">Question (masked) · hash</th>
                <th className="px-4 py-2.5 font-medium">Retrieved documents</th>
                <th className="px-4 py-2.5 font-medium">Excluded by permissions</th>
                <th className="px-4 py-2.5 font-medium">Outcome</th>
                <th className="px-4 py-2.5 font-medium">Latency</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => {
                const person = names.get(entry.actor);
                const docs = [...new Set(entry.retrieved_document_ids)].map((id) => titles.get(id) ?? id.slice(0, 8));
                return (
                  <tr key={entry.id} className="border-b border-zinc-100 align-top last:border-0">
                    <td className="px-4 py-2.5 font-mono text-xs whitespace-nowrap text-zinc-500">{entry.ts.replace("T", " ").slice(0, 19)}</td>
                    <td className="px-4 py-2.5">
                      <span className="flex items-center gap-2">
                        {person && <Avatar name={person.name} email={person.email} size="sm" />}
                        <span className="text-zinc-800">{person?.name ?? entry.actor}</span>
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={cn("rounded-md px-1.5 py-0.5 text-xs font-medium", EVENT_STYLE[entry.event] ?? "bg-zinc-100")}>
                        {entry.event}
                      </span>
                    </td>
                    <td className="max-w-80 px-4 py-2.5">
                      <span className="block text-zinc-800">{entry.question_preview ?? detailText(entry)}</span>
                      {entry.question_hash && <span className="font-mono text-[11px] text-zinc-400">{entry.question_hash.slice(0, 16)}</span>}
                    </td>
                    <td className="max-w-72 px-4 py-2.5 text-xs text-zinc-600">{docs.join(", ") || "–"}</td>
                    <td className="px-4 py-2.5 text-center">
                      {entry.candidates_excluded === null ? (
                        "–"
                      ) : (
                        <span className={cn("font-mono", entry.candidates_excluded > 0 ? "font-semibold text-amber-700" : "text-zinc-500")}>
                          {entry.candidates_excluded}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-zinc-600">
                      {entry.outcome}
                      {entry.cache_hit ? " · cache" : ""}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-zinc-500">{ms(entry.latency_ms)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {entries.length === 0 && <p className="p-6 text-sm text-zinc-500">No entries yet.</p>}
        </div>
      </main>
    </div>
  );
}

function detailText(entry: AuditEntry): string {
  const details = entry.details as { document_id?: string; chunks?: number };
  if (entry.event === "acl_update") return `ACL changed (${details.chunks ?? "?"} chunk rows)`;
  if (entry.event === "delete") return "Document deleted";
  return entry.event;
}
