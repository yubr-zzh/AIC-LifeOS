import React from "react";
import type { PermissionRequest, Store } from "../state/store";
import { Panel } from "../components/Panel";
import { StatusPill } from "../components/StatusPill";
import { IconApprove, IconReject } from "../components/Icons";

interface Props {
  store: Store;
}

export function PermissionsPanel({ store }: Props) {
  const { state } = store;
  const list = state.permissions;

  return (
    <Panel
      title="Permissions"
      subtitle="tool execution · skill installation — kept separate"
      source={state.ui.dataMode}
      dense
    >
      {list.length === 0 ? (
        <div className="state-empty">no pending permission requests</div>
      ) : (
        <div className="scroll" style={{ padding: "4px 6px", display: "flex", flexDirection: "column", gap: 8 }}>
          {list.map((p) => (
            <PermCard key={p.id} perm={p} store={store} />
          ))}
        </div>
      )}
    </Panel>
  );
}

function PermCard({ perm, store }: { perm: PermissionRequest; store: Store }) {
  const kindLabel = perm.kind === "tool_execution" ? "tool execution" : "skill installation";
  return (
    <div
      className="card"
      style={{
        borderColor: "rgba(185,133,255,0.4)",
        background: "var(--st-confirm-soft)",
      }}
    >
      <div className="row between">
        <div className="col" style={{ gap: 2 }}>
          <span className="mono" style={{ color: "var(--violet)", fontSize: 12 }}>{kindLabel}</span>
          <span className="mono muted" style={{ fontSize: 10 }}>id {perm.id}</span>
        </div>
        <StatusPill kind="confirm" label={perm.decision.replace(/_/g, " ")} size="sm" />
      </div>
      <p style={{ margin: "6px 0 0", fontSize: 12 }}>subject: <span className="mono">{perm.subject}</span></p>
      <p className="muted" style={{ margin: "2px 0 0", fontSize: 12 }}>{perm.reason}</p>
      <div className="row" style={{ marginTop: 8, gap: 6 }}>
        <button className="violet" onClick={() => store.resolvePermission(perm.id, "allow")}>
          <span className="row" style={{ gap: 6 }}>
            <IconApprove size={11} /> Allow
          </span>
        </button>
        <button className="ghost danger" onClick={() => store.resolvePermission(perm.id, "deny")}>
          <span className="row" style={{ gap: 6 }}>
            <IconReject size={11} /> Deny
          </span>
        </button>
        <span className="mono muted" style={{ fontSize: 10 }}>
          (POST /permissions/{perm.id}/confirm — not implemented yet)
        </span>
      </div>
    </div>
  );
}
