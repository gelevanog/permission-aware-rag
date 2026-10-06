// The same access rule as clearance/acl.py, for the admin page's "who can read this" preview.
import type { Acl } from "./api";

export function canRead(principals: string[], allow: string[], deny: string[]): boolean {
  const reader = new Set(principals);
  if (deny.some((p) => reader.has(p))) return false;
  return allow.some((p) => reader.has(p));
}

export type Access = "full" | "partial" | "none";

/** Full: every section readable; partial: some sections hidden by an override; none: nothing readable. */
export function accessFor(principals: string[], acl: Acl, headings: string[]): Access {
  const body = canRead(principals, acl.allow, acl.deny);
  const sectionResults = acl.sections
    .filter((rule) => headings.some((h) => h.toLowerCase() === rule.heading.toLowerCase()))
    .map((rule) => canRead(principals, rule.allow, [...acl.deny, ...rule.deny]));
  const all = [body, ...sectionResults];
  if (all.every(Boolean)) return "full";
  if (all.some(Boolean)) return "partial";
  return "none";
}

export function principalLabel(principal: string): string {
  if (principal.startsWith("user:")) return principal.slice(5).split("@")[0];
  return principal.replace(/^group:/, "");
}
