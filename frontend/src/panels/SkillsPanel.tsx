import React from "react";
import type { SkillCandidate, SkillRegistryState } from "../api/types";
import type { Store } from "../state/store";
import { Panel } from "../components/Panel";
import { StatusPill } from "../components/StatusPill";
import { IconApprove, IconReject } from "../components/Icons";

interface Props {
  store: Store;
}

export function SkillsPanel({ store }: Props) {
  const { state } = store;
  const s = state.skills;
  return (
    <Panel
      title="Skills"
      subtitle="approved registry · pending candidates · permission review"
      source={state.ui.dataMode}
      dense
    >
      <div style={{ padding: "6px 8px 4px" }}>
        <SectionHeader label="Approved" count={s.approved.length} />
      </div>
      <div className="scroll" style={{ padding: "4px 8px 8px", display: "flex", flexDirection: "column", gap: 6, maxHeight: "30%", overflow: "auto" }}>
        {s.approved.length === 0 ? <div className="state-empty">no approved skills</div> : s.approved.map((sk) => (
          <SkillCard key={sk.id} skill={sk} />
        ))}
      </div>
      <div style={{ padding: "6px 8px 4px", borderTop: "1px solid var(--bd-1)" }}>
        <SectionHeader label="Pending candidates" count={s.pending.length} />
      </div>
      <div className="scroll" style={{ padding: "4px 8px 8px", display: "flex", flexDirection: "column", gap: 8 }}>
        {s.pending.length === 0 ? <div className="state-empty">no pending candidates</div> : s.pending.map((sk) => (
          <PendingCard key={sk.id} skill={sk} store={store} />
        ))}
      </div>
    </Panel>
  );
}

function SectionHeader({ label, count }: { label: string; count: number }) {
  return (
    <div className="row between">
      <span className="uppercase">{label}</span>
      <span className="mono muted" style={{ fontSize: 11 }}>{count}</span>
    </div>
  );
}

function SkillCard({ skill }: { skill: SkillCandidate }) {
  return (
    <div className="card-flat">
      <div className="row between">
        <span className="mono" style={{ color: "var(--accent)", fontSize: 12 }}>
          {skill.name}
        </span>
        <StatusPill kind={`risk-${skill.risk}` as "risk-low" | "risk-medium" | "risk-high"} label={`risk: ${skill.risk}`} />
      </div>
      <p className="muted" style={{ margin: "4px 0 0", fontSize: 12 }}>{skill.description}</p>
    </div>
  );
}

function PendingCard({ skill, store }: { skill: SkillCandidate; store: Store }) {
  const decision = skill.review?.decision ?? "allow";
  const pill = decision === "requires_confirmation" ? "confirm" : decision === "deny" ? "failed" : "done";
  return (
    <div
      style={{
        border: `1px solid ${decision === "requires_confirmation" ? "rgba(185,133,255,0.4)" : "var(--bd-2)"}`,
        borderRadius: "var(--r-2)",
        padding: "10px 12px",
        background: decision === "requires_confirmation" ? "var(--st-confirm-bg)" : "var(--bg-2)",
      }}
    >
      <div className="row between">
        <div className="col" style={{ gap: 2 }}>
          <span className="mono" style={{ color: "var(--accent)", fontSize: 12 }}>{skill.name}</span>
          <span className="mono muted" style={{ fontSize: 10 }}>id {skill.id}</span>
        </div>
        <StatusPill kind={`risk-${skill.risk}` as "risk-low" | "risk-medium" | "risk-high"} label={`risk: ${skill.risk}`} />
      </div>
      <p style={{ margin: "6px 0 0", fontSize: 12 }}>{skill.description}</p>
      <div className="row" style={{ marginTop: 6, gap: 6, flexWrap: "wrap" }}>
        <span className="mono muted" style={{ fontSize: 10 }}>source: {skill.source}</span>
        <span className={`pill ${pill}`}><span className="dot" />{decision.replace(/_/g, " ")}</span>
        {skill.review?.reason ? <span className="mono muted" style={{ fontSize: 10 }}>{skill.review.reason}</span> : null}
      </div>
      <div className="row" style={{ marginTop: 8, gap: 6 }}>
        <button onClick={() => store.approveSkill(skill.id)}>
          <span className="row" style={{ gap: 6 }}>
            <IconApprove size={11} /> Approve install
          </span>
        </button>
        <button className="ghost danger" onClick={() => store.rejectSkill(skill.id)}>
          <span className="row" style={{ gap: 6 }}>
            <IconReject size={11} /> Reject
          </span>
        </button>
        <span className="mono muted" style={{ fontSize: 10 }}>
          (POST /skills/pending/{skill.id}/approve — not implemented yet)
        </span>
      </div>
    </div>
  );
}
