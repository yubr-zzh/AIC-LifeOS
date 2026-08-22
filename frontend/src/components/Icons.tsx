import React from "react";

interface IconProps {
  size?: number;
  className?: string;
  title?: string;
}

const wrap = (path: React.ReactNode, viewBox = "0 0 24 24", p: IconProps) => (
  <svg
    width={p.size ?? 14}
    height={p.size ?? 14}
    viewBox={viewBox}
    fill="none"
    stroke="currentColor"
    strokeWidth={1.6}
    strokeLinecap="round"
    strokeLinejoin="round"
    className={p.className}
    aria-hidden={p.title ? undefined : true}
    role={p.title ? "img" : undefined}
  >
    {p.title ? <title>{p.title}</title> : null}
    {path}
  </svg>
);

export const IconSend = (p: IconProps) =>
  wrap(<path d="M3 11l18-8-8 18-2-8-8-2z" />, "0 0 24 24", p);

export const IconRefresh = (p: IconProps) =>
  wrap(
    <>
      <path d="M3 12a9 9 0 0 1 15.5-6.3L21 8" />
      <path d="M21 3v5h-5" />
      <path d="M21 12a9 9 0 0 1-15.5 6.3L3 16" />
      <path d="M3 21v-5h5" />
    </>,
    "0 0 24 24",
    p,
  );

export const IconCopy = (p: IconProps) =>
  wrap(
    <>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" />
    </>,
    "0 0 24 24",
    p,
  );

export const IconRun = (p: IconProps) =>
  wrap(<path d="M5 4l14 8-14 8V4z" />, "0 0 24 24", p);

export const IconInspect = (p: IconProps) =>
  wrap(
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.3-4.3" />
    </>,
    "0 0 24 24",
    p,
  );

export const IconApprove = (p: IconProps) =>
  wrap(<path d="M4 12l5 5L20 6" />, "0 0 24 24", p);

export const IconReject = (p: IconProps) =>
  wrap(
    <>
      <path d="M5 5l14 14" />
      <path d="M19 5L5 19" />
    </>,
    "0 0 24 24",
    p,
  );

export const IconChevron = (p: IconProps) =>
  wrap(<path d="M9 6l6 6-6 6" />, "0 0 24 24", p);

export const IconBolt = (p: IconProps) =>
  wrap(<path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z" />, "0 0 24 24", p);

export const IconList = (p: IconProps) =>
  wrap(
    <>
      <path d="M8 6h13" />
      <path d="M8 12h13" />
      <path d="M8 18h13" />
      <circle cx="4" cy="6" r="1" />
      <circle cx="4" cy="12" r="1" />
      <circle cx="4" cy="18" r="1" />
    </>,
    "0 0 24 24",
    p,
  );
