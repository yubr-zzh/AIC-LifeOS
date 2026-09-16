import React, { useCallback, useEffect, useState } from "react";
import type { LifecycleStage, MemoryCandidate, MemoryEntry } from "../api/types";
import { LIFECYCLE_STAGES } from "../api/types";
import type { Store } from "../state/store";
import { getMemoryMarkdown, importMemoryMarkdown } from "../api/client";
import { Panel } from "../components/Panel";
import { IconApprove, IconReject } from "../components/Icons";

type Tab =
  | "user"
  | "project"
  | "feedback"
  | "reference"
  | "candidates"
  | "backups"
  | "markdown";

const TABS: { id: Tab; label: string }[] = [
  { id: "user", label: "User" },
  { id: "project", label: "Project" },
  { id: "feedback", label: "Feedback" },
  { id: "reference", label: "Reference" },
  { id: "candidates", label: "Candidates" },
  { id: "backups", label: "Backups" },
  { id: "markdown", label: "Markdown" },
];

interface Props {
  store: Store;
}

export function MemoryPanel({ store }: Props) {
  const { state } = store;
  const [tab, setTab] = useState<Tab>("candidates");
  const mem = state.memory;

  return (
    <Panel
      title="Memory"
      subtitle="lifecycle · user / project / feedback / reference / candidates · markdown editable"
      source={state.ui.dataMode}
      dense
    >
      <div className="row" style={{ gap: 4, padding: "0 6px 8px", flexWrap: "wrap" }}>
        {TABS.map((t) => {
          const active = tab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={active ? "primary" : "ghost"}
              style={{ borderRadius: "var(--r-pill)", padding: "3px 10px", fontSize: 11 }}
            >
              {t.label}
              {t.id === "candidates" && mem.candidates.length > 0 ? (
                <span className="mono" style={{ marginLeft: 6, opacity: 0.8 }}>
                  {mem.candidates.length}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      {tab === "user" ? <EntryList entries={mem.user} empty="no user memory yet" /> : null}
      {tab === "project" ? <EntryList entries={mem.project} empty="no project memory yet" /> : null}
      {tab === "feedback" ? <EntryList entries={mem.feedback} empty="no feedback memory yet" /> : null}
      {tab === "reference" ? <EntryList entries={mem.reference} empty="no reference memory yet" /> : null}
      {tab === "markdown" ? <MarkdownTab store={store} /> : null}
      {tab === "candidates" ? (
        <CandidateList candidates={mem.candidates} store={store} />
      ) : null}
      {tab === "backups" ? (
        <div className="scroll" style={{ padding: "4px 6px" }}>
          {mem.backups.length === 0 ? (
            <div className="state-empty">no backups yet</div>
          ) : (
            mem.backups.map((b, i) => (
              <div key={i} className="row between" style={{ padding: "6px 0", borderBottom: "1px solid var(--bd-1)" }}>
                <span className="mono" style={{ fontSize: 11 }}>
                  backup #{mem.backups.length - i}
                </span>
                <span className="mono muted" style={{ fontSize: 11 }} title={b.created_at}>
                  {new Date(b.created_at).toLocaleString()}
                </span>
              </div>
            ))
          )}
        </div>
      ) : null}
    </Panel>
  );
}

function MarkdownTab({ store }: { store: Store }) {
  const [md, setMd] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [message, setMessage] = useState("");

  const load = useCallback(() => {
    setStatus("loading");
    getMemoryMarkdown()
      .then((r) => {
        setMd(r.markdown);
        setStatus("idle");
      })
      .catch((e) => {
        setStatus("error");
        setMessage(e instanceof Error ? e.message : String(e));
      });
  }, []);

  useEffect(load, [load]);

  const save = () => {
    importMemoryMarkdown(md)
      .then((r) => {
        setMessage(`imported — user:${r.categories.user} project:${r.categories.project} feedback:${r.categories.feedback} reference:${r.categories.reference}`);
        void store.refreshAll();
      })
      .catch((e) => {
        setMessage(`import failed: ${e instanceof Error ? e.message : String(e)}`);
      });
  };

  return (
    <div className="col" style={{ padding: "4px 6px", gap: 6 }}>
      <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
        <button onClick={load} disabled={status === "loading"}>Refresh</button>
        <button className="ghost" onClick={save}>Import edited markdown</button>
        {message ? <span className="mono muted" style={{ fontSize: 10 }}>{message}</span> : null}
      </div>
      <textarea
        className="mono"
        value={md}
        onChange={(e) => setMd(e.target.value)}
        placeholder={status === "error" ? `failed to load: ${message}` : "loading markdown…"}
        spellCheck={false}
        style={{ width: "100%", minHeight: 220, fontSize: 11, lineHeight: 1.5, resize: "vertical" }}
      />
      <div className="mono muted" style={{ fontSize: 10 }}>
        memory.md mirror — edit and import to write back to memory.json (readable / editable / auditable)
      </div>
    </div>
  );
}

function EntryList({ entries, empty }: { entries: MemoryEntry[]; empty: string }) {
  if (entries.length === 0) return <div className="state-empty">{empty}</div>;
  return (
    <div className="scroll" style={{ padding: "4px 6px", display: "flex", flexDirection: "column", gap: 6 }}>
      {entries.map((e) => (
        <div key={e.id} className="card-flat">
          <div className="row between">
            <span className="mono" style={{ color: "var(--accent)", fontSize: 11 }}>
              {e.source}
            </span>
            <span className="mono muted" style={{ fontSize: 11 }}>
              {new Date(e.created_at).toLocaleString()}
            </span>
          </div>
          <pre
            className="mono"
            style={{
              margin: "6px 0 0",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              fontSize: 11,
              color: "var(--fg-2)",
            }}
          >
            {JSON.stringify(e.content, null, 2)}
          </pre>
          {e.trace_id ? (
            <div className="mono muted" style={{ fontSize: 10, marginTop: 4 }}>trace {e.trace_id}</div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function CandidateList({ candidates, store }: { candidates: MemoryCandidate[]; store: Store }) {
  if (candidates.length === 0)
    return <div className="state-empty">no candidates — run a chat turn and <span className="mono">run BG once</span> to generate one</div>;
  return (
    <div className="scroll" style={{ padding: "4px 6px", display: "flex", flexDirection: "column", gap: 8 }}>
      {candidates.map((c) => (
        <CandidateCard key={c.id} c={c} store={store} />
      ))}
    </div>
  );
}

function CandidateCard({ c, store }: { c: MemoryCandidate; store: Store }) {
  // Synthetic lifecycle: candidate -> validated -> backed_up -> applied -> vector_upserted -> cache_invalidated.
  // We compute "how far along" from status + presence in project memory.
  const inProject = store.state.memory.project.some((p) => p.id === c.id);
  let stages: LifecycleStage[] = ["candidate"];
  if (c.status === "rejected") {
    stages = ["candidate"];
  } else if (c.status === "committed" || inProject) {
    stages = [
      "candidate",
      "validated",
      "backed_up",
      "applied",
      "vector_upserted",
      "cache_invalidated",
    ];
  }

  return (
    <div
      style={{
        border: `1px solid ${c.status === "committed" ? "rgba(78,201,138,0.4)" : c.status === "rejected" ? "rgba(255,110,110,0.4)" : "var(--bd-2)"}`,
        background: "var(--bg-2)",
        borderRadius: "var(--r-2)",
        padding: "10px 12px",
      }}
    >
      <div className="row between" style={{ marginBottom: 6 }}>
        <div className="row" style={{ gap: 8 }}>
          <span className="mono" style={{ color: "var(--accent)", fontSize: 12 }}>
            {c.source}
          </span>
          <span className="mono dim" style={{ fontSize: 11 }}>{c.id.slice(0, 13)}…</span>
        </div>
        <span className={`pill sm ${c.status === "committed" ? "done" : c.status === "rejected" ? "failed" : "pending"}`}>
          <span className="dot" />
          {c.status}
        </span>
      </div>
      <pre
        className="mono"
        style={{ margin: 0, fontSize: 11, color: "var(--fg-2)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}
      >
        {JSON.stringify(c.content, null, 2)}
      </pre>
      <div className="row" style={{ gap: 4, marginTop: 8, flexWrap: "wrap" }}>
        {LIFECYCLE_STAGES.map((s) => (
          <span
            key={s}
            className={`pill sm ${stages.includes(s) ? "done" : "idle"}`}
            title={s}
          >
            <span className="dot" />
            {s}
          </span>
        ))}
      </div>
      {c.status === "candidate" ? (
        <div className="row" style={{ gap: 6, marginTop: 10 }}>
          <button disabled={store.state.ui.dataMode !== "backend"} onClick={() => void store.approveCandidate(c.id)} title="Commit memory candidate">
            <span className="row" style={{ gap: 6 }}>
              <IconApprove size={11} /> Approve
            </span>
          </button>
          <button className="ghost danger" disabled={store.state.ui.dataMode !== "backend"} onClick={() => void store.rejectCandidate(c.id)}>
            <span className="row" style={{ gap: 6 }}>
              <IconReject size={11} /> Reject
            </span>
          </button>
          <span className="mono muted" style={{ fontSize: 10 }}>
            {store.state.ui.dataMode === "backend" ? "saved by backend" : "preview data — actions unavailable"}
          </span>
        </div>
      ) : null}
    </div>
  );
}
