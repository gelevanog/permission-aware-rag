"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { AnswerView } from "@/components/AnswerView";
import { Avatar } from "@/components/Avatar";
import { Header } from "@/components/Header";
import { CheckIcon, FileIcon, LockIcon, SendIcon, SpinnerIcon } from "@/components/icons";
import { PrincipalChip } from "@/components/PrincipalChip";
import { accessFor, type Access } from "@/lib/acl";
import { api, ApiError, type Acl, type AclUpdateResult, type AdminDocument, type Directory } from "@/lib/api";
import { cn, ms } from "@/lib/format";
import { useSession } from "@/lib/session";
import { useAsk } from "@/lib/useAsk";

const ADMIN = "ian.brooks@fernhill.test";

export default function AdminPage() {
  const { user, setUser, tokenFor, users } = useSession();
  const [documents, setDocuments] = useState<AdminDocument[]>([]);
  const [directory, setDirectory] = useState<Directory | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [forbidden, setForbidden] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!user) return;
    try {
      const token = await tokenFor(user.email);
      const [docs, dir] = await Promise.all([api.adminDocuments(token), api.adminDirectory(token)]);
      setDocuments(docs);
      setDirectory(dir);
      setForbidden(false);
      setSelectedId((current) => current ?? docs.find((d) => d.external_id.includes("career-ladder"))?.id ?? docs[0]?.id ?? null);
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) setForbidden(true);
    }
  }, [user, tokenFor]);

  useEffect(() => {
    void load();
  }, [load]);

  const groups = useMemo(() => {
    const visible = documents.filter((d) => `${d.path} ${d.title}`.toLowerCase().includes(filter.toLowerCase()));
    const byFolder = new Map<string, AdminDocument[]>();
    for (const doc of visible) byFolder.set(doc.path || "(root)", [...(byFolder.get(doc.path || "(root)") ?? []), doc]);
    return [...byFolder.entries()];
  }, [documents, filter]);

  const selected = documents.find((d) => d.id === selectedId) ?? null;

  if (forbidden) {
    return (
      <div className="min-h-screen">
        <Header />
        <main className="mx-auto max-w-xl px-6 py-24 text-center">
          <span className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-zinc-100 text-zinc-600">
            <LockIcon width={22} height={22} />
          </span>
          <h1 className="mt-4 text-lg font-semibold">Access administration needs the it-admins group</h1>
          <p className="mt-2 text-sm text-zinc-500">
            {user?.name} is signed in. Administrators manage who can read what; they get no read-everything bypass in
            chat.
          </p>
          <button
            type="button"
            onClick={() => setUser(ADMIN)}
            className="mt-5 rounded-xl bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-800"
          >
            Switch to Ian Brooks (IT Administrator)
          </button>
        </main>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      <main className="mx-auto grid w-full max-w-[1400px] flex-1 grid-cols-[340px_minmax(0,1fr)] gap-6 px-6 py-6">
        <aside className="flex max-h-[calc(100vh-7rem)] flex-col rounded-2xl border border-zinc-200 bg-white">
          <div className="border-b border-zinc-100 p-4">
            <h1 className="text-sm font-semibold text-zinc-900">Documents and ACLs</h1>
            <p className="mt-0.5 text-xs text-zinc-500">
              {documents.length} documents · edit an ACL and the next question sees the change
            </p>
            <input
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Filter…"
              className="mt-3 w-full rounded-lg border border-zinc-200 px-3 py-1.5 text-sm outline-none focus:border-emerald-400"
            />
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            {groups.map(([folder, docs]) => (
              <div key={folder} className="mb-2">
                <p className="px-2 py-1 text-[11px] font-semibold tracking-wide text-zinc-400 uppercase">{folder}</p>
                {docs.map((doc) => (
                  <button
                    key={doc.id}
                    type="button"
                    onClick={() => setSelectedId(doc.id)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition",
                      doc.id === selectedId ? "bg-emerald-50 text-emerald-900" : "text-zinc-700 hover:bg-zinc-50",
                    )}
                  >
                    <FileIcon width={14} height={14} className="shrink-0 text-zinc-400" />
                    <span className="flex-1 truncate">{doc.title}</span>
                    {doc.acl.sections.length > 0 && (
                      <span title="Has a restricted section" className="rounded bg-amber-100 px-1 text-[10px] font-semibold text-amber-800">
                        §
                      </span>
                    )}
                    {doc.acl.deny.length > 0 && (
                      <span title="Has deny entries" className="rounded bg-rose-100 px-1 text-[10px] font-semibold text-rose-700">
                        deny
                      </span>
                    )}
                  </button>
                ))}
              </div>
            ))}
          </div>
          <div className="border-t border-zinc-100 p-3">
            <button
              type="button"
              onClick={async () => {
                if (!user) return;
                const result = await api.resync(await tokenFor(user.email));
                setNotice(`Re-read the source folder: ${result.acl_updated} ACLs restored, ${result.unchanged} unchanged.`);
                await load();
              }}
              className="w-full rounded-lg border border-zinc-200 px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50"
            >
              Restore source ACLs (re-sync the folder)
            </button>
          </div>
        </aside>

        <section className="space-y-5">
          {notice && (
            <p className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm text-emerald-900">
              <CheckIcon /> {notice}
            </p>
          )}
          {selected && directory && user && (
            <Editor
              key={`${selected.id}-${selected.acl_version}`}
              document={selected}
              directory={directory}
              token={() => tokenFor(user.email)}
              onSaved={async (result) => {
                setNotice(
                  `Saved version ${result.acl_version}: ${result.chunks_updated} chunk ACL rows rewritten in ${ms(result.elapsed_ms)}. Nothing was re-embedded; the next question sees it.`,
                );
                await load();
              }}
            />
          )}
          {selected && directory && <TryIt users={users} document={selected} tokenFor={tokenFor} />}
        </section>
      </main>
    </div>
  );
}

function Editor({
  document,
  directory,
  token,
  onSaved,
}: {
  document: AdminDocument;
  directory: Directory;
  token: () => Promise<string>;
  onSaved: (result: AclUpdateResult) => Promise<void>;
}) {
  const [acl, setAcl] = useState<Acl>(document.acl);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = JSON.stringify(acl) !== JSON.stringify(document.acl);
  const options = useMemo(
    () => [
      ...directory.groups.map((g) => `group:${g.name}`),
      ...directory.users.map((u) => `user:${u.email}`),
    ],
    [directory],
  );

  const update = (list: "allow" | "deny", values: string[]) => setAcl((current) => ({ ...current, [list]: values }));
  const updateSection = (index: number, values: string[]) =>
    setAcl((current) => ({
      ...current,
      sections: current.sections.map((s, i) => (i === index ? { ...s, allow: values } : s)),
    }));

  return (
    <div className="rounded-2xl border border-zinc-200 bg-white">
      <div className="flex items-start justify-between gap-4 border-b border-zinc-100 px-6 py-4">
        <div>
          <h2 className="text-base font-semibold text-zinc-900">{document.title}</h2>
          <p className="mt-0.5 font-mono text-xs text-zinc-500">
            {document.source}:{document.external_id} · {document.chunks} chunks · ACL version {document.acl_version}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {dirty && (
            <button type="button" onClick={() => setAcl(document.acl)} className="rounded-lg px-3 py-1.5 text-sm text-zinc-600 hover:bg-zinc-100">
              Reset
            </button>
          )}
          <button
            type="button"
            disabled={!dirty || saving}
            onClick={async () => {
              setSaving(true);
              setError(null);
              try {
                await onSaved(await api.updateAcl(await token(), document.id, acl));
              } catch (err) {
                setError(err instanceof Error ? err.message : String(err));
              } finally {
                setSaving(false);
              }
            }}
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-700 px-3.5 py-1.5 text-sm font-medium text-white hover:bg-emerald-800 disabled:bg-zinc-200 disabled:text-zinc-400"
          >
            {saving && <SpinnerIcon width={14} height={14} />} Save ACL
          </button>
        </div>
      </div>
      {error && <p className="mx-6 mt-4 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}
      <div className="grid grid-cols-[minmax(0,1fr)_300px] gap-6 p-6">
        <div className="space-y-5">
          <PrincipalList label="Allow" tone="allow" values={acl.allow} options={options} onChange={(v) => update("allow", v)} />
          <PrincipalList label="Deny (always wins)" tone="deny" values={acl.deny} options={options} onChange={(v) => update("deny", v)} />
          <div>
            <p className="text-[11px] font-semibold tracking-wide text-zinc-500 uppercase">Section overrides</p>
            {acl.sections.length === 0 && <p className="mt-1 text-xs text-zinc-400">None: every section follows the document ACL.</p>}
            {acl.sections.map((section, index) => (
              <div key={section.heading} className="mt-2 rounded-xl border border-amber-200 bg-amber-50/50 p-3">
                <p className="text-sm font-medium text-zinc-800">
                  § {section.heading} <span className="font-normal text-zinc-500">replaces the allow list for this section</span>
                </p>
                <div className="mt-2">
                  <PrincipalList
                    label=""
                    tone="section"
                    values={section.allow}
                    options={options}
                    onChange={(v) => updateSection(index, v)}
                  />
                </div>
                <button
                  type="button"
                  onClick={() => setAcl((current) => ({ ...current, sections: current.sections.filter((_, i) => i !== index) }))}
                  className="mt-2 text-xs text-rose-700 hover:underline"
                >
                  Remove override
                </button>
              </div>
            ))}
            {document.headings.filter((h) => !acl.sections.some((s) => s.heading.toLowerCase() === h.toLowerCase())).length > 0 && (
              <select
                value=""
                onChange={(event) =>
                  event.target.value &&
                  setAcl((current) => ({
                    ...current,
                    sections: [...current.sections, { heading: event.target.value, allow: [...current.allow], deny: [] }],
                  }))
                }
                className="mt-2 rounded-lg border border-zinc-200 px-2 py-1 text-xs text-zinc-600"
              >
                <option value="">+ Restrict a section…</option>
                {document.headings.map((h) => (
                  <option key={h} value={h}>
                    {h}
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>
        <WhoCanRead acl={acl} document={document} directory={directory} />
      </div>
    </div>
  );
}

function PrincipalList({
  label,
  tone,
  values,
  options,
  onChange,
}: {
  label: string;
  tone: "allow" | "deny" | "section";
  values: string[];
  options: string[];
  onChange: (values: string[]) => void;
}) {
  return (
    <div>
      {label && <p className="text-[11px] font-semibold tracking-wide text-zinc-500 uppercase">{label}</p>}
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        {values.map((p) => (
          <PrincipalChip key={p} principal={p} tone={tone} onRemove={() => onChange(values.filter((v) => v !== p))} />
        ))}
        {values.length === 0 && <span className="text-xs text-zinc-400">nobody</span>}
        <select
          value=""
          onChange={(event) => event.target.value && onChange([...values, event.target.value].sort())}
          className="rounded-md border border-dashed border-zinc-300 bg-white px-1.5 py-0.5 text-[11px] text-zinc-500"
        >
          <option value="">+ add</option>
          {options
            .filter((o) => !values.includes(o))
            .map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
        </select>
      </div>
    </div>
  );
}

const ACCESS_STYLE: Record<Access, string> = {
  full: "bg-emerald-100 text-emerald-800",
  partial: "bg-amber-100 text-amber-800",
  none: "bg-zinc-100 text-zinc-500",
};

function WhoCanRead({ acl, document, directory }: { acl: Acl; document: AdminDocument; directory: Directory }) {
  return (
    <div className="rounded-xl border border-zinc-200 p-3">
      <p className="text-[11px] font-semibold tracking-wide text-zinc-500 uppercase">Who can read it (preview)</p>
      <ul className="mt-2 space-y-1">
        {directory.users.map((u) => {
          const access = accessFor(u.principals, acl, document.headings);
          return (
            <li key={u.email} className="flex items-center gap-2 text-sm">
              <Avatar name={u.name} email={u.email} size="sm" />
              <span className="flex-1 truncate text-zinc-700">{u.name}</span>
              <span className={cn("rounded-md px-1.5 py-0.5 text-[11px] font-medium", ACCESS_STYLE[access])}>
                {access === "partial" ? "without restricted §" : access}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function TryIt({
  users,
  document,
  tokenFor,
}: {
  users: { email: string; name: string; title: string }[];
  document: AdminDocument;
  tokenFor: (email: string) => Promise<string>;
}) {
  const [email, setEmail] = useState("dan.kim@fernhill.test");
  const [question, setQuestion] = useState("");
  const ask = useAsk(tokenFor);
  useEffect(() => {
    setQuestion(document.external_id.includes("career-ladder") ? "What is the salary band for a Senior Engineer (L4)?" : `What does "${document.title}" say?`);
  }, [document]);
  return (
    <div className="rounded-2xl border border-zinc-200 bg-white p-5">
      <p className="text-sm font-semibold text-zinc-900">Try it: ask as someone else</p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void ask.ask(email, question);
        }}
        className="mt-3 flex items-center gap-2"
      >
        <select value={email} onChange={(event) => setEmail(event.target.value)} className="rounded-lg border border-zinc-200 px-2 py-2 text-sm">
          {users.map((u) => (
            <option key={u.email} value={u.email}>
              {u.name} · {u.title}
            </option>
          ))}
        </select>
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          className="flex-1 rounded-lg border border-zinc-200 px-3 py-2 text-sm outline-none focus:border-emerald-400"
        />
        <button type="submit" className="flex size-9 items-center justify-center rounded-lg bg-zinc-900 text-white" aria-label="Ask">
          <SendIcon />
        </button>
      </form>
      {ask.state && (
        <div className="mt-4">
          <AnswerView state={ask.state} compact />
        </div>
      )}
    </div>
  );
}
