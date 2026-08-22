import React from "react";
import type { EventStatus, ChatAgentStatus, GlobalAgentStatus, RiskLevel } from "../api/types";

type PillKind = EventStatus | ChatAgentStatus | GlobalAgentStatus | RiskLevel | "idle" | "confirm" | "risk-low" | "risk-medium" | "risk-high";

interface Props {
  kind: PillKind;
  label?: string;
  size?: "sm" | "md" | "lg";
}

export function StatusPill({ kind, label, size = "md" }: Props) {
  // Map all variants to one of the css classes defined in global.css.
  const cls = ["pending", "processing", "done", "failed", "idle", "confirm", "risk-low", "risk-medium", "risk-high"].includes(kind)
    ? kind
    : "idle";
  const sizeCls = size === "sm" ? " sm" : size === "lg" ? " lg" : "";
  const text = label ?? kind.replace(/_/g, " ");
  return (
    <span className={`pill ${cls}${sizeCls}`}>
      <span className="dot" />
      {text}
    </span>
  );
}
