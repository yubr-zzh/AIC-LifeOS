import React, { useEffect, useState } from "react";
import type { TraceRecord } from "../api/types";
import { getTrace } from "../api/client";
import type { Store } from "../state/store";
import { Panel } from "../components/Panel";
import { CopyId } from "../components/CopyId";
import { SourceBadge } from "../components/SourceBadge";

interface Props {
  store: Store;
}

export function TracePanel({ store }: Props) {
  const { state } = store;
  const id = state.ui.selectedTraceId;
  const [trace, setTrace] = useState<TraceRecord | null>(null);
  const [source, setSource] = useState<"backend" | "preview">("preview");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!id) {
      setTrace(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    getTrace(id)
      .then((r) => {
        if (cancelled) return;
        setTrace(r.data);
        setSource(r.source);
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (!id) {
    return (
      <Panel title="Trace Inspector" subtitle="no trace selected">
        <div className="state-empty">click a <span className="mono">trace</span> chip in the chat or event queue</div>
      </Panel>
    );
  }

  return (
    <Panel
      title="Trace Inspector"
      subtitle={id}
      source={source}
      actions={<CopyId value={id} />}
    >
      {loading ? (
        <div className="state-empty">loading…</div>
      ) : !trace ? (
        <div className="state-empty">no trace detail</div>
      ) : (
        <div className="col" style={{ gap: 10 }}>
          <Field label="input" value={trace.input} />
          <Field label="created" value={trace.created} mono />
          <div className="col" style={{ gap: 6 }}>
            <span className="mono" style={{ fontSize: 11, color: "var(--fg-2)", textTransform: "uppercase", letterSpacing: "0.1em" }}>
              events ({trace.events.length})
            </span>
            {trace.events.map((ev, i) => (
              <div key={i} style={{ border: "1px solid var(--bd-1)", borderRadius: "var(--r-1)", padding: "8px 10px", background: "var(--bg-2)" }}>
                <div className="row between">
                  <span className="mono" style={{ color: "var(--accent)", fontSize: 12 }}>{ev.name}</span>
                  <span className="mono muted" style={{ fontSize: 10 }}>{new Date(ev.created).toLocaleTimeString()}</span>
                </div>
                <pre className="mono" style={{ margin: "4px 0 0", fontSize: 11, color: "var(--fg-2)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                  {JSON.stringify(ev.data, null, 2)}
                </pre>
              </div>
            ))}
          </div>
          <div className="mono muted" style={{ fontSize: 10 }}>
            source: {source === "backend" ? "GET /traces/{trace_id}" : "preview — /traces endpoint not implemented"}
          </div>
        </div>
      )}
    </Panel>
  );
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="col" style={{ gap: 2 }}>
      <span className="mono" style={{ fontSize: 10, color: "var(--fg-2)", textTransform: "uppercase", letterSpacing: "0.1em" }}>{label}</span>
      <span className={mono ? "mono" : ""} style={{ fontSize: 12, color: "var(--fg-1)", wordBreak: "break-word" }}>{value}</span>
    </div>
  );
}
