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

export const IconHome = (p: IconProps) =>
  wrap(<path d="M3 10.5L12 3l9 7.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 19.5v-9z" />, "0 0 24 24", p);

export const IconMessage = (p: IconProps) =>
  wrap(<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 4v-4.1A2.5 2.5 0 0 1 4 13.5v-8z" />, "0 0 24 24", p);

export const IconCalendar = (p: IconProps) =>
  wrap(<><rect x="3.5" y="5" width="17" height="16" rx="2" /><path d="M7 3v4M17 3v4M3.5 9.5h17" /></>, "0 0 24 24", p);

export const IconBook = (p: IconProps) =>
  wrap(<><path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v17H6.5A2.5 2.5 0 0 0 4 21.5v-17z" /><path d="M4 18.5A2.5 2.5 0 0 1 6.5 16H20" /></>, "0 0 24 24", p);

export const IconSpark = (p: IconProps) =>
  wrap(<><path d="M12 3l1.3 5.7L19 10l-5.7 1.3L12 17l-1.3-5.7L5 10l5.7-1.3L12 3z" /><path d="M19 16l.6 2.4L22 19l-2.4.6L19 22l-.6-2.4L16 19l2.4-.6L19 16z" /></>, "0 0 24 24", p);

export const IconSun = (p: IconProps) =>
  wrap(<><circle cx="12" cy="12" r="3.5" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>, "0 0 24 24", p);

/** 半圆 / 主题切换图标 — 用于设置页"外观"分类。SVG 保证对齐 baseline。 */
export const IconContrast = (p: IconProps) =>
  wrap(
    <>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 4a8 8 0 0 0 0 16z" fill="currentColor" stroke="none" />
    </>,
    "0 0 24 24",
    p,
  );

export const IconSettings = (p: IconProps) =>
  wrap(<><path d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-1.8 1.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-2.5V20a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1-1.8-1.8.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.6-1H6v-2.5h.2a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1 1.8-1.8.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.6V5h2.5v.2a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1 1.8 1.8-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v2.5h-.2a1.7 1.7 0 0 0-1.6 1z" /></>, "0 0 24 24", p);

export const IconArrowRight = (p: IconProps) =>
  wrap(
    <>
      <path d="M5 12h14" />
      <path d="M13 5l7 7-7 7" />
    </>,
    "0 0 24 24",
    p,
  );

export const IconArrowUpRight = (p: IconProps) =>
  wrap(
    <>
      <path d="M7 17L17 7" />
      <path d="M8 7h9v9" />
    </>,
    "0 0 24 24",
    p,
  );

export const IconCheck = (p: IconProps) =>
  wrap(<path d="M4 12l5 5L20 6" />, "0 0 24 24", p);

export const IconPlus = (p: IconProps) =>
  wrap(
    <>
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </>,
    "0 0 24 24",
    p,
  );

export const IconTrash = (p: IconProps) =>
  wrap(
    <>
      <path d="M3 6h18" />
      <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
      <path d="M5 6l1 14a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1l1-14" />
      <path d="M10 11v6M14 11v6" />
    </>,
    "0 0 24 24",
    p,
  );

export const IconInbox = (p: IconProps) =>
  wrap(
    <>
      <path d="M3 13l3-8h12l3 8" />
      <path d="M3 13v6a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-6" />
      <path d="M3 13h5l1.5 2.5h5L16 13h5" />
    </>,
    "0 0 24 24",
    p,
  );

export const IconLeaf = (p: IconProps) =>
  wrap(
    <>
      <path d="M4 20c0-8 6-14 16-16-2 10-8 16-16 16z" />
      <path d="M4 20l9-9" />
    </>,
    "0 0 24 24",
    p,
  );

export const IconCircleDot = (p: IconProps) =>
  wrap(
    <>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="3" fill="currentColor" stroke="none" />
    </>,
    "0 0 24 24",
    p,
  );

export const IconPause = (p: IconProps) =>
  wrap(
    <>
      <path d="M9 5v14" />
      <path d="M15 5v14" />
    </>,
    "0 0 24 24",
    p,
  );

export const IconSlash = (p: IconProps) =>
  wrap(
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M6.5 17.5l11-11" />
    </>,
    "0 0 24 24",
    p,
  );
