"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/format";
import { useSession } from "@/lib/session";
import { CpuIcon, LogoIcon } from "./icons";
import { UserPicker } from "./UserSwitcher";

const NAV = [
  { href: "/", label: "Chat" },
  { href: "/compare", label: "Two users" },
  { href: "/admin", label: "Access admin" },
  { href: "/eval", label: "Evaluation" },
  { href: "/audit", label: "Audit log" },
];

export function Header({ showUser = true }: { showUser?: boolean }) {
  const pathname = usePathname();
  const { users, user, setUser, health } = useSession();
  return (
    <header className="sticky top-0 z-20 border-b border-zinc-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-[1400px] items-center gap-6 px-6">
        <Link href="/" className="flex items-center gap-2">
          <span className="flex size-8 items-center justify-center rounded-lg bg-emerald-700 text-white">
            <LogoIcon width={18} height={18} />
          </span>
          <span className="text-[17px] font-semibold tracking-tight text-zinc-900">Clearance</span>
        </Link>
        <nav className="flex items-center gap-1">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "rounded-lg px-3 py-1.5 text-sm font-medium whitespace-nowrap transition",
                pathname === item.href ? "bg-zinc-900 text-white" : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900",
              )}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          {health && (
            <span
              title={`Embeddings: ${health.embedding_model}`}
              className={cn(
                "hidden items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium lg:inline-flex",
                health.model_is_local
                  ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                  : "border-amber-200 bg-amber-50 text-amber-800",
              )}
            >
              <CpuIcon width={13} height={13} />
              {health.model_is_local ? "Local model" : "Cloud model"} · {health.model.split("/").slice(1).join("/") || health.model}
            </span>
          )}
          {showUser && <UserPicker users={users} value={user} onChange={setUser} />}
        </div>
      </div>
    </header>
  );
}
