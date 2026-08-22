import React from "react";
import type { EventRecord, Store } from "../state/store";
import { Panel } from "../components/Panel";
import { StatusPill } from "../components/StatusPill";
import { IconRun, IconRefresh, IconInspect } from "../components/Icons";

interface Props {
  store: Store;
}

export function EventsPanel({ store }: Props) {
  const { state, runBackground, refreshAll } = store;
  const events = state.events;

  return (
    <Panel
      title="Event Queue"
      subtitle="durable .lifeos/events.json"
      source={state.ui.dataMode}
      actions={
        <>
          <button className="ghost" onClick={() => void refreshAll()} disabled={state.loading.events} title="Refresh">
            <span className="row" style={{ gap: 6 }}>
              <IconRefresh size={12} /> Refresh
            </span>
          </button>
          <button
            className="primary"
            onClick={() => void runBackground()}
            disabled={state.loading.background}
            title="POST /background/run-once"
          >
            <span className="row" style={{ gap: 6 }}>
              <IconRun size={12} /> Run BG once
            </span>
          </button>
        </>
      }
      dense
    >
      {events.length === 0 ? (
        <div className="state-empty">no events yet — send a message to publish one</div>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>status</th>
              <th>type</th>
              <th>trace</th>
              <th style={{ textAlign: "right" }}>attempts</th>
              <th style={{ textAlign: "right" }}>updated</th>
              <th style={{ width: 36 }}></th>
            </tr>
          </thead>
          <tbody>
            {events.map((e) => (
              <EventRow key={e.id} event={e} store={store} />
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function EventRow({ event, store }: { event: EventRecord; store: Store }) {
  const isFailed = event.status === "failed";
  return (
    <tr style={isFailed ? { background: "var(--st-failed-soft)" } : undefined}>
      <td>
        <StatusPill kind={event.status} size="sm" />
      </td>
      <td>
        <span className="mono">{event.type}</span>
      </td>
      <td>
        {event.trace_id ? (
          <button
            className="ghost compact"
            onClick={() => store.selectTrace(event.trace_id ?? null)}
            title={event.trace_id}
          >
            <span className="mono truncate" style={{ maxWidth: 120 }}>
              {event.trace_id.slice(0, 13)}…
            </span>
          </button>
        ) : (
          <span className="dim mono">—</span>
        )}
      </td>
      <td style={{ textAlign: "right" }}>
        <span className="mono num">{event.attempts}</span>
      </td>
      <td style={{ textAlign: "right" }}>
        <span className="mono muted" title={event.updated_at}>
          {new Date(event.updated_at).toLocaleTimeString()}
        </span>
      </td>
      <td style={{ textAlign: "right" }}>
        <button
          className="ghost compact"
          onClick={() => store.selectTrace(event.trace_id ?? null)}
          title="Inspect trace"
          aria-label="Inspect trace"
        >
          <IconInspect size={11} />
        </button>
      </td>
    </tr>
  );
}
