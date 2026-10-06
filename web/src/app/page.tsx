"use client";

import { useEffect, useRef, useState } from "react";

import { AnswerView, type AnswerState } from "@/components/AnswerView";
import { Avatar } from "@/components/Avatar";
import { Header } from "@/components/Header";
import { LogoIcon, SendIcon } from "@/components/icons";
import { TracePanel } from "@/components/TracePanel";
import { api, streamAsk, type Trace } from "@/lib/api";
import { useSession } from "@/lib/session";

interface Turn {
  question: string;
  state: AnswerState;
  trace: Trace | null;
}

const SUGGESTIONS: Record<string, string[]> = {
  default: [
    "How many days of paid time off do we get?",
    "What is the salary band for a Senior Engineer (L4)?",
    "What's the codename of the deal leadership is working on?",
    "What is the per diem when travelling in Portugal?",
  ],
};

export default function ChatPage() {
  const { user, tokenFor, error } = useSession();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [principals, setPrincipals] = useState<string[]>([]);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // A different person is signed in: start a fresh conversation and show their principals.
    setTurns([]);
    setSelected(null);
    setPrincipals([]);
    if (!user) return;
    tokenFor(user.email)
      .then((token) => api.me(token))
      .then((me) => setPrincipals(me.principals))
      .catch(() => setPrincipals([]));
  }, [user, tokenFor]);

  useEffect(() => bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }), [turns]);

  const update = (index: number, patch: Partial<Turn>) =>
    setTurns((current) => current.map((turn, i) => (i === index ? { ...turn, ...patch } : turn)));

  const ask = async (question: string) => {
    if (!user || !question.trim() || busy) return;
    const index = turns.length;
    setTurns((current) => [...current, { question, state: { status: "searching" }, trace: null }]);
    setSelected(index);
    setInput("");
    setBusy(true);
    let text = "";
    try {
      const token = await tokenFor(user.email);
      await streamAsk(token, question, (event) => {
        if (event.type === "trace") update(index, { trace: event.trace });
        else if (event.type === "token") {
          text += event.text;
          update(index, { state: { status: "streaming", text } });
        } else if (event.type === "done") update(index, { state: { status: "done", answer: event.answer }, trace: event.answer.trace });
        else if (event.type === "error") update(index, { state: { status: "error", error: event.error } });
      });
    } catch (err) {
      update(index, { state: { status: "error", error: err instanceof Error ? err.message : String(err) } });
    } finally {
      setBusy(false);
    }
  };

  const activeTrace = selected !== null ? (turns[selected]?.trace ?? null) : null;

  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      <main className="mx-auto grid w-full max-w-[1400px] flex-1 grid-cols-[minmax(0,1fr)_380px] gap-6 px-6 py-6">
        <section className="flex min-h-[calc(100vh-7rem)] flex-col rounded-2xl border border-zinc-200 bg-white">
          <div className="flex-1 space-y-6 overflow-y-auto px-8 py-6">
            {error && <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">API not reachable: {error}</p>}
            {turns.length === 0 && user && (
              <div className="mx-auto max-w-xl py-14 text-center">
                <span className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-700">
                  <LogoIcon width={26} height={26} />
                </span>
                <h1 className="mt-4 text-xl font-semibold text-zinc-900">Ask Fernhill&apos;s documents as {user.name}</h1>
                <p className="mt-2 text-sm text-zinc-500">
                  Answers come only from documents {user.name.split(" ")[0]} is allowed to read. Switch the user in the
                  top right to see the same company through someone else&apos;s permissions.
                </p>
                <div className="mt-6 flex flex-wrap justify-center gap-2">
                  {SUGGESTIONS.default.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => void ask(s)}
                      className="rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-sm text-zinc-700 transition hover:border-emerald-300 hover:bg-emerald-50"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {turns.map((turn, index) => (
              <div key={index} className="space-y-3" onClick={() => setSelected(index)}>
                <div className="flex justify-end">
                  <div className="flex max-w-[80%] items-start gap-2">
                    <div className="rounded-2xl rounded-br-md bg-zinc-900 px-4 py-2.5 text-white">{turn.question}</div>
                    {user && <Avatar name={user.name} email={user.email} size="sm" />}
                  </div>
                </div>
                <div className="flex gap-3">
                  <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-emerald-700 text-white">
                    <LogoIcon width={15} height={15} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <AnswerView state={turn.state} />
                  </div>
                </div>
              </div>
            ))}
            <div ref={bottom} />
          </div>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void ask(input);
            }}
            className="border-t border-zinc-100 p-4"
          >
            <div className="flex items-center gap-2 rounded-2xl border border-zinc-200 bg-white px-4 py-2 shadow-xs focus-within:border-emerald-400 focus-within:ring-2 focus-within:ring-emerald-100">
              <input
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder={user ? `Ask as ${user.name}…` : "Loading users…"}
                className="flex-1 bg-transparent py-1.5 text-[15px] outline-none placeholder:text-zinc-400"
              />
              <button
                type="submit"
                disabled={busy || !input.trim()}
                className="flex size-9 items-center justify-center rounded-xl bg-emerald-700 text-white transition hover:bg-emerald-800 disabled:bg-zinc-200 disabled:text-zinc-400"
                aria-label="Ask"
              >
                <SendIcon />
              </button>
            </div>
            <p className="mt-2 text-center text-xs text-zinc-400">
              Runs on your own infrastructure: local embeddings, a local model, PostgreSQL. Nothing leaves the network.
            </p>
          </form>
        </section>
        <aside className="h-fit rounded-2xl border border-zinc-200 bg-white p-5">
          <h2 className="mb-4 flex items-center justify-between text-sm font-semibold text-zinc-900">
            Permission trace
            {selected !== null && turns.length > 1 && (
              <span className="text-xs font-normal text-zinc-400">question {selected + 1}</span>
            )}
          </h2>
          <TracePanel trace={activeTrace} principals={principals} />
        </aside>
      </main>
    </div>
  );
}
