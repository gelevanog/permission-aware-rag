"use client";

import { useCallback, useRef, useState } from "react";

import type { AnswerState } from "@/components/AnswerView";
import { streamAsk, type Trace } from "./api";

/** Streams one answer for one user: state for the answer, the permission trace as soon as retrieval is done. */
export function useAsk(tokenFor: (email: string) => Promise<string>) {
  const [state, setState] = useState<AnswerState | null>(null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const controller = useRef<AbortController | null>(null);

  const ask = useCallback(
    async (email: string, question: string): Promise<AnswerState> => {
      controller.current?.abort();
      const abort = new AbortController();
      controller.current = abort;
      setState({ status: "searching" });
      setTrace(null);
      let text = "";
      let final: AnswerState = { status: "error", error: "No answer" };
      try {
        const token = await tokenFor(email);
        await streamAsk(
          token,
          question,
          (event) => {
            if (event.type === "trace") setTrace(event.trace);
            else if (event.type === "token") {
              text += event.text;
              setState({ status: "streaming", text });
            } else if (event.type === "replace") {
              text = event.text;
            } else if (event.type === "done") {
              final = { status: "done", answer: event.answer };
              setTrace(event.answer.trace);
              setState(final);
            } else if (event.type === "error") {
              final = { status: "error", error: event.error };
              setState(final);
            }
          },
          abort.signal,
        );
      } catch (error) {
        if (abort.signal.aborted) return final;
        final = { status: "error", error: error instanceof Error ? error.message : String(error) };
        setState(final);
      }
      return final;
    },
    [tokenFor],
  );

  const reset = useCallback(() => {
    controller.current?.abort();
    setState(null);
    setTrace(null);
  }, []);

  return { state, trace, ask, reset };
}
