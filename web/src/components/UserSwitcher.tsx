"use client";

import { useEffect, useRef, useState } from "react";

import type { DemoUser } from "@/lib/api";
import { cn } from "@/lib/format";
import { Avatar } from "./Avatar";
import { ChevronIcon } from "./icons";

export function UserPicker({
  users,
  value,
  onChange,
  label = "View as",
  align = "right",
}: {
  users: DemoUser[];
  value: DemoUser | null;
  onChange: (email: string) => void;
  label?: string;
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2.5 rounded-xl border border-zinc-200 bg-white py-1.5 pr-2.5 pl-1.5 text-left shadow-xs transition hover:border-zinc-300"
      >
        {value ? <Avatar name={value.name} email={value.email} /> : <span className="size-8 rounded-full bg-zinc-100" />}
        <span className="min-w-0">
          <span className="block text-[10px] font-medium tracking-wide text-zinc-400 uppercase">{label}</span>
          <span className="block truncate text-sm font-medium text-zinc-900">
            {value ? `${value.name} · ${value.title}` : "Loading…"}
          </span>
        </span>
        <ChevronIcon className="ml-1 text-zinc-400" />
      </button>
      {open && (
        <div
          className={cn(
            "absolute z-30 mt-2 max-h-[70vh] w-80 overflow-y-auto rounded-xl border border-zinc-200 bg-white p-1.5 shadow-lg",
            align === "right" ? "right-0" : "left-0",
          )}
        >
          {users.map((user) => (
            <button
              key={user.email}
              type="button"
              onClick={() => {
                onChange(user.email);
                setOpen(false);
              }}
              className={cn(
                "flex w-full items-start gap-2.5 rounded-lg px-2 py-2 text-left transition hover:bg-zinc-50",
                value?.email === user.email && "bg-emerald-50 hover:bg-emerald-50",
              )}
            >
              <Avatar name={user.name} email={user.email} size="sm" />
              <span className="min-w-0">
                <span className="block text-sm font-medium text-zinc-900">
                  {user.name} <span className="font-normal text-zinc-500">· {user.title}</span>
                </span>
                <span className="block text-xs text-zinc-500">{user.persona}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
