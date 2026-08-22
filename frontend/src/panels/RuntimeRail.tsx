import React from "react";
import type { Store } from "../state/store";
import { Panel } from "../components/Panel";
import { StatusPill } from "../components/StatusPill";

interface Props {
  store: Store;
}

export function RuntimeRail({ store }: Props) {
  const { state, busCounts } = store;
  const chat = state.ui.chatStatus;
  const bus = state.ui.busStatus;
  const g = state.ui.globalStatus;

  const globalLabel: Record<typeof g, string> = {
    idle: "idle",
    polling: "polling",
    reflecting: "reflecting",
    writing_memory: "writing memory",
    detecting_skills: "detecting skills",
    reviewing: "reviewing",
  };

  const chatLabel: Record<typeof chat, string> = {
    idle: "idle",
    thinking: "thinking",
    tool_calling: "tool calling",
    responded: "responded",
    error: "error",
  };

  const busLabel: Record<typeof bus, string> = {
    stable: "stable",
    queued: "queued",
    processing: "processing",
    failed: "has failures",
  };

  return (
    <Panel title="Runtime Rail" subtitle="foreground / background state" dense>
      <div style={{ padding: "4px 4px 8px", display: "flex", flexDirection: "column", gap: 10 }}>
        <Row label="Chat Agent" hint={chatLabel[chat]}>
          <StatusPill kind={chat === "error" ? "failed" : chat === "idle" ? "idle" : "processing"} label={chatLabel[chat]} />
        </Row>
        <Row label="Event Bus" hint={`${busCounts.pending} pending · ${busCounts.processing} processing · ${busCounts.done} done · ${busCounts.failed} failed`}>
          <StatusPill
            kind={bus === "failed" ? "failed" : bus === "processing" ? "processing" : bus === "queued" ? "pending" : "done"}
            label={busLabel[bus]}
          />
        </Row>
        <Row label="Global Agent" hint={globalLabel[g]}>
          <StatusPill kind={g === "idle" ? "idle" : "processing"} label={globalLabel[g]} />
        </Row>
        <Row label="Data Mode" hint={state.ui.dataMode === "backend" ? "reading real backend" : "missing endpoints; using preview"}>
          <span className={`pill ${state.ui.dataMode === "backend" ? "done" : "pending"}`}>
            <span className="dot" />
            {state.ui.dataMode}
          </span>
        </Row>
        <Row label="Last BG Run" hint={state.ui.lastRunAt ? new Date(state.ui.lastRunAt).toLocaleTimeString() : "never"}>
          <span className="mono muted" style={{ fontSize: 11 }}>
            {state.ui.lastRunAt ? new Date(state.ui.lastRunAt).toLocaleTimeString() : "—"}
          </span>
        </Row>
      </div>
    </Panel>
  );
}

function Row({ label, hint, children }: { label: string; hint: string; children: React.ReactNode }) {
  return (
    <div className="row between" style={{ gap: 10 }}>
      <div className="col" style={{ gap: 2, minWidth: 0 }}>
        <span className="uppercase">{label}</span>
        <span className="muted" style={{ fontSize: 11 }}>{hint}</span>
      </div>
      <div style={{ flexShrink: 0 }}>{children}</div>
    </div>
  );
}
