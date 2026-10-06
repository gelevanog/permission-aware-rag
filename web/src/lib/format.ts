export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export function ms(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  if (value >= 1000) return `${(value / 1000).toFixed(1)} s`;
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ms`;
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "–";
  return `${(value * 100).toFixed(digits)}%`;
}

const AVATAR_COLORS = [
  "bg-emerald-600",
  "bg-sky-600",
  "bg-amber-600",
  "bg-rose-600",
  "bg-violet-600",
  "bg-teal-600",
  "bg-orange-600",
  "bg-cyan-700",
  "bg-fuchsia-600",
  "bg-lime-700",
  "bg-slate-600",
];

export function avatarColor(email: string): string {
  let hash = 0;
  for (const char of email) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
}
