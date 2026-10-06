import { avatarColor, cn, initials } from "@/lib/format";

export function Avatar({ name, email, size = "md" }: { name: string; email: string; size?: "sm" | "md" | "lg" }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-white",
        avatarColor(email),
        size === "sm" && "size-6 text-[10px]",
        size === "md" && "size-8 text-xs",
        size === "lg" && "size-10 text-sm",
      )}
    >
      {initials(name)}
    </span>
  );
}
