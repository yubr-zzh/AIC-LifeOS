import React from "react";
import type { Store } from "../state/store";
import { SourceBadge } from "../components/SourceBadge";
import { IconBolt } from "../components/Icons";

interface Props {
  store: Store;
}

export function TopBar({ store }: Props) {
  const { state } = store;
  const error = state.ui.lastError;
  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        gap: 14,
        padding: "11px 16px",
        borderBottom: "1px solid var(--bd-1)",
        background: "linear-gradient(180deg, var(--bg-2) 0%, var(--bg-1) 100%)",
        position: "sticky",
        top: 0,
        zIndex: 5,
      }}
    >
      <div className="row" style={{ gap: 8 }}>
        <span style={{ color: "var(--accent)" }}>
          <IconBolt size={16} />
        </span>
        <div className="col" style={{ gap: 0 }}>
          <span style={{ fontWeight: 600, letterSpacing: "0.04em" }}>LifeOS Console</span>
          <span className="mono muted" style={{ fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase" }}>
            Chat Agent · Global Agent · Reliable Event Bus
          </span>
        </div>
      </div>
      <div className="grow" />
      <div className="row" style={{ gap: 12 }}>
        {error ? (
          <span className="pill failed" title={error}>
            <span className="dot" />
            error
          </span>
        ) : null}
        <SourceBadge source={state.ui.dataMode} />
        <span className="mono muted" style={{ fontSize: 11 }}>
          backend: <span style={{ color: "var(--fg-2)" }}>http://127.0.0.1:8765</span>
        </span>
      </div>
    </header>
  );
}
