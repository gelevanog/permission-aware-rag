// The same access rule as clearance/acl.py, for the admin page's "who can read this" preview.
import type { Acl } from "./api";

export function canRead(principals: string[], allow: string[], deny: string[]): boolean {
  const reader = new Set(principals);
  if (deny.some((p) => reader.has(p))) return false;
  return allow.some((p) => reader.has(p));
}

export type Access = "full" | "body" | "section" | "none";

/**
 * full: everything; body: the document but not its restricted section(s); section: only a restricted section
 * (granted by an override, e.g. HR reading the salary bands of an engineering doc); none: nothing.
 */
export function accessFor(principals: string[], acl: Acl, headings: string[]): Access {
  const body = canRead(principals, acl.allow, acl.deny);
  const sections = acl.sections
    .filter((rule) => headings.some((h) => h.toLowerCase() === rule.heading.toLowerCase()))
    .map((rule) => canRead(principals, rule.allow, [...acl.deny, ...rule.deny]));
  if (body && sections.every(Boolean)) return "full";
  if (body) return "body";
  if (sections.some(Boolean)) return "section";
  return "none";
}

export function principalLabel(principal: string): string {
  if (principal.startsWith("user:")) return principal.slice(5).split("@")[0];
  return principal.replace(/^group:/, "");
}
