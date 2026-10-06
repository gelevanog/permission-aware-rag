"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AnswerView } from "@/components/AnswerView";
import { Avatar } from "@/components/Avatar";
import { Header } from "@/components/Header";
import { LockIcon, SendIcon } from "@/components/icons";
import { PrincipalChip } from "@/components/PrincipalChip";
import { UserPicker } from "@/components/UserSwitcher";
import type { DemoUser, Trace } from "@/lib/api";
import { useSession } from "@/lib/session";
import { useAsk } from "@/lib/useAsk";

const PRESETS: { question: string; left: string; right: string }[] = [
  { question: "What is the salary band for a Senior Engineer (L4)?", left: "erin.walsh", right: "dan.kim" },
  { question: "What's the codename of the deal leadership is working on?", left: "hana.sato", right: "alice.chen" },
  { question: "What is the absolute floor price for the Growth tier?", left: "julia.romero", right: "frank.moreau" },
  { question: "How do I get emergency break-glass access to production?", left: "dan.kim", right: "bob.tanner" },
  { question: "Are there any layoffs or reorganizations planned?", left: "carol.diaz", right: "erin.walsh" },
];

const email = (local: string) => `${local}@fernhill.test`;

export default function ComparePage() {
  return (
    <Suspense>
      <Compare />
    </Suspense>
  );
}

function Compare() {
  const { users, tokenFor } = useSession();
  const params = useSearchParams(); // ?q=...&a=erin.walsh&b=dan.kim preselects a comparison
  const [left, setLeft] = useState(email(params.get("a") ?? PRESETS[0].left));
  const [right, setRight] = useState(email(params.get("b") ?? PRESETS[0].right));
  const [question, setQuestion] = useState(params.get("q") ?? PRESETS[0].question);
  const leftAsk = useAsk(tokenFor);
  const rightAsk = useAsk(tokenFor);
  const busy = [leftAsk.state, rightAsk.state].some((s) => s?.status === "searching" || s?.status === "streaming");

  const run = (q: string, a = left, b = right) => {
    if (!q.trim()) return;
    void leftAsk.ask(a, q);
    void rightAsk.ask(b, q);
  };

  return (
    <div className="flex min-h-screen flex-col">
      <Header showUser={false} />
      <main className="mx-auto w-full max-w-[1400px] flex-1 px-6 py-6">
        <div className="rounded-2xl border border-zinc-200 bg-white p-5">
          <div className="flex items-baseline justify-between">
            <h1 className="text-lg font-semibold text-zinc-900">Same question, two users</h1>
            <p className="text-sm text-zinc-500">Each answer is computed from that person&apos;s permissions only.</p>
          </div>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              run(question);
            }}
            className="mt-4 flex items-center gap-2 rounded-2xl border border-zinc-200 px-4 py-2 focus-within:border-emerald-400 focus-within:ring-2 focus-within:ring-emerald-100"
          >
            <input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              className="flex-1 bg-transparent py-1.5 text-[15px] outline-none"
              placeholder="Ask a question…"
            />
            <button
              type="submit"
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-700 px-3.5 py-2 text-sm font-medium text-white hover:bg-emerald-800 disabled:bg-zinc-300"
            >
              Ask both <SendIcon width={14} height={14} />
            </button>
          </form>
          <div className="mt-3 flex flex-wrap gap-2">
            {PRESETS.map((preset) => (
              <button
                key={preset.question}
                type="button"
                onClick={() => {
                  setQuestion(preset.question);
                  setLeft(email(preset.left));
                  setRight(email(preset.right));
                  run(preset.question, email(preset.left), email(preset.right));
                }}
                className="rounded-full border border-zinc-200 px-3 py-1 text-xs text-zinc-600 transition hover:border-emerald-300 hover:bg-emerald-50"
              >
                {preset.question}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-5">
          <Column users={users} email={left} onUser={setLeft} ask={leftAsk} />
          <Column users={users} email={right} onUser={setRight} ask={rightAsk} />
        </div>
      </main>
    </div>
  );
}

function Column({
  users,
  email: address,
  onUser,
  ask,
}: {
  users: DemoUser[];
  email: string;
  onUser: (email: string) => void;
  ask: ReturnType<typeof useAsk>;
}) {
  const user = users.find((u) => u.email === address) ?? null;
  return (
    <section className="flex flex-col rounded-2xl border border-zinc-200 bg-white">
      <div className="flex items-center justify-between gap-3 border-b border-zinc-100 px-5 py-4">
        <UserPicker users={users} value={user} onChange={onUser} label="Asked by" align="left" />
        {user && <span className="text-right text-xs text-zinc-500">{user.persona}</span>}
      </div>
      <div className="min-h-64 flex-1 px-5 py-5">
        {ask.state ? (
          <div className="flex gap-3">
            {user && <Avatar name={user.name} email={user.email} size="sm" />}
            <div className="min-w-0 flex-1">
              <AnswerView state={ask.state} compact />
            </div>
          </div>
        ) : (
          <p className="text-sm text-zinc-400">Pick a question above.</p>
        )}
      </div>
      <MiniTrace trace={ask.trace} />
    </section>
  );
}

function MiniTrace({ trace }: { trace: Trace | null }) {
  if (!trace) return <div className="h-14 border-t border-zinc-100" />;
  return (
    <div className="space-y-2 border-t border-zinc-100 bg-zinc-50/60 px-5 py-3 text-xs text-zinc-600">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span>
          <strong className="text-zinc-900">{trace.searchable_documents}</strong> documents searchable
        </span>
        {trace.excluded_documents !== null && (
          <span className="inline-flex items-center gap-1">
            <LockIcon width={12} height={12} /> {trace.excluded_documents} not accessible
          </span>
        )}
        <span>{trace.retrieved.filter((r) => r.in_context).length} passages given to the model</span>
      </div>
      <div className="flex flex-wrap gap-1">
        {trace.principals.map((p) => (
          <PrincipalChip key={p} principal={p} />
        ))}
      </div>
    </div>
  );
}
