import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function base(props: IconProps) {
  return {
    width: 16,
    height: 16,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    ...props,
  };
}

export const LogoIcon = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="M12 3 4.5 6v5.5c0 4.6 3.1 8.1 7.5 9.5 4.4-1.4 7.5-4.9 7.5-9.5V6L12 3Z" />
    <circle cx="12" cy="10.5" r="2" />
    <path d="M12 12.5v3" />
  </svg>
);
export const LockIcon = (props: IconProps) => (
  <svg {...base(props)}>
    <rect x="5" y="11" width="14" height="9" rx="2" />
    <path d="M8 11V8a4 4 0 0 1 8 0v3" />
  </svg>
);
export const FileIcon = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
    <path d="M14 3v5h5" />
  </svg>
);
export const SendIcon = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);
export const ChevronIcon = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="m6 9 6 6 6-6" />
  </svg>
);
export const SpinnerIcon = (props: IconProps) => (
  <svg {...base(props)} className={`animate-spin ${props.className ?? ""}`}>
    <path d="M21 12a9 9 0 1 1-6.2-8.6" />
  </svg>
);
export const CheckIcon = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="m5 12 5 5L20 7" />
  </svg>
);
export const XIcon = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="M18 6 6 18M6 6l12 12" />
  </svg>
);
export const CpuIcon = (props: IconProps) => (
  <svg {...base(props)}>
    <rect x="6" y="6" width="12" height="12" rx="2" />
    <path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" />
  </svg>
);
export const EyeOffIcon = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M9.9 5.1A9.8 9.8 0 0 1 12 5c5 0 9 4.5 10 7-.4 1-1.2 2.3-2.4 3.5M6.3 6.3C4.2 7.7 2.7 9.8 2 12c1 2.5 5 7 10 7 1.7 0 3.2-.5 4.6-1.2" />
  </svg>
);
