import React, { useState } from "react";
import { IconCopy } from "./Icons";

interface Props {
  value: string;
  className?: string;
}

export function CopyId({ value, className }: Props) {
  const [copied, setCopied] = useState(false);
  const onClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(value).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 900);
      },
      () => undefined,
    );
  };
  return (
    <span
      className={`mono truncate ${className ?? ""}`}
      title={value}
      onClick={onClick}
      style={{
        cursor: "pointer",
        display: "inline-flex",
        gap: 6,
        alignItems: "center",
        padding: "2px 6px",
        borderRadius: "var(--r-0)",
        background: "var(--bg-2)",
        border: "1px solid var(--bd-1)",
        transition: "background var(--t-fast), border-color var(--t-fast)",
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLElement).style.background = "var(--bg-3)";
        (e.currentTarget as HTMLElement).style.borderColor = "var(--bd-3)";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLElement).style.background = "var(--bg-2)";
        (e.currentTarget as HTMLElement).style.borderColor = "var(--bd-1)";
      }}
    >
      <span className="truncate" style={{ maxWidth: 220 }}>
        {value}
      </span>
      <IconCopy size={11} />
      {copied ? <span style={{ color: "var(--st-done)" }}>copied</span> : null}
    </span>
  );
}
