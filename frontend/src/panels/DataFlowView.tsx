import React from "react";
import type { PipelineStage, PipelineStageId } from "../api/types";
import type { Store } from "../state/store";

const STAGES: PipelineStage[] = [
  { id: "user_input", label: "User Input", detail: "your message" },
  { id: "chat_agent", label: "Chat Agent", detail: "foreground path" },
  { id: "memory_retrieve", label: "Memory Retrieve", detail: "store snapshot" },
  { id: "llm_tool", label: "LLM / Tool", detail: "completion + tools" },
  { id: "response", label: "Response", detail: "back to UI" },
  { id: "event_bus", label: "Event Bus", detail: ".lifeos/events.json" },
  { id: "global_agent", label: "Global Agent", detail: "background loop" },
  { id: "reflection", label: "Reflection", detail: "summarize turn" },
  { id: "memory_candidate", label: "Memory Candidate", detail: "2-phase write" },
  { id: "security_review", label: "Security Review", detail: "permission check" },
  { id: "commit", label: "Commit / Invalidate", detail: "vector + cache" },
];

interface Props {
  store: Store;
}

export function DataFlowView({ store }: Props) {
  const { state } = store;
  const active = state.pipeline.active;
  const visited = new Set(state.pipeline.visited);

  return (
    <section className="panel" style={{ minHeight: 0 }}>
      <header className="panel-header">
        <div className="col" style={{ gap: 2 }}>
          <span className="panel-title">Data Flow</span>
          <span className="panel-subtitle">active stage lights up · visited stages remain tinted</span>
        </div>
        <span className="mono muted" style={{ fontSize: 11 }}>
          {state.pipeline.visited.length || 0} / {STAGES.length} stages
        </span>
      </header>
      <div className="panel-body" style={{ padding: "12px" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(11, minmax(0, 1fr))",
            gap: 6,
          }}
        >
          {STAGES.map((s, i) => (
            <StageCell
              key={s.id}
              stage={s}
              isActive={active === s.id}
              isVisited={visited.has(s.id)}
              idx={i}
            />
          ))}
        </div>
      </div>
    </section>
  );
}

function StageCell({ stage, isActive, isVisited, idx }: { stage: PipelineStage; isActive: boolean; isVisited: boolean; idx: number }) {
  return (
    <div
      className={`col ${isActive ? "stage-active" : ""}`}
      style={{
        background: isVisited ? "var(--bg-2)" : "var(--bg-1)",
        border: `1px solid ${isActive ? "var(--accent)" : isVisited ? "var(--bd-2)" : "var(--bd-1)"}`,
        borderRadius: "var(--r-2)",
        padding: "7px 9px",
        minHeight: 58,
        transition: "background 200ms ease, border-color 200ms ease, box-shadow 200ms ease",
      }}
    >
      <span className="mono" style={{ fontSize: 10, color: "var(--fg-3)" }}>
        {String(idx + 1).padStart(2, "0")}
      </span>
      <span className="mono" style={{ fontSize: 11, color: isActive ? "var(--accent)" : "var(--fg-1)" }}>
        {stage.label}
      </span>
      <span className="muted" style={{ fontSize: 10, lineHeight: 1.3 }}>{stage.detail}</span>
    </div>
  );
}
