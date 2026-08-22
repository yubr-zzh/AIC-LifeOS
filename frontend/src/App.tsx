import React, { useEffect, useState } from "react";
import { useStore } from "./state/store";
import { TopBar } from "./panels/TopBar";
import { ChatPanel } from "./panels/ChatPanel";
import { RuntimeRail } from "./panels/RuntimeRail";
import { DataFlowView } from "./panels/DataFlowView";
import { EventsPanel } from "./panels/EventsPanel";
import { MemoryPanel } from "./panels/MemoryPanel";
import { SkillsPanel } from "./panels/SkillsPanel";
import { TracePanel } from "./panels/TracePanel";
import { PermissionsPanel } from "./panels/PermissionsPanel";

type MobileTab = "chat" | "runtime" | "events" | "memory" | "skills" | "trace" | "permissions";

const MOBILE_TABS: { id: MobileTab; label: string }[] = [
  { id: "chat", label: "Chat" },
  { id: "runtime", label: "Runtime" },
  { id: "events", label: "Events" },
  { id: "memory", label: "Memory" },
  { id: "skills", label: "Skills" },
  { id: "permissions", label: "Perms" },
  { id: "trace", label: "Trace" },
];

export default function App() {
  const store = useStore();
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < 980);
  const [activeTab, setActiveTab] = useState<MobileTab>("chat");

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 980);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  if (isMobile) {
    return (
      <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
        <TopBar store={store} />
        <nav className="tabbar" aria-label="Sections">
          {MOBILE_TABS.map((t) => (
            <button
              key={t.id}
              className={activeTab === t.id ? "primary" : "ghost"}
              onClick={() => setActiveTab(t.id)}
              aria-current={activeTab === t.id ? "page" : undefined}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <main style={{ flex: 1, minHeight: 0, padding: 10, display: "flex", overflow: "hidden" }}>
          <MobileTabPanel tab={activeTab} store={store} />
        </main>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <TopBar store={store} />
      <main
        style={{
          flex: 1,
          minHeight: 0,
          display: "grid",
          gridTemplateColumns: "240px minmax(0, 1fr) 320px 320px",
          gridTemplateRows: "auto minmax(0, 1fr)",
          gap: 10,
          padding: 10,
          overflow: "hidden",
          gridTemplateAreas: `
            "rail flow trace trace"
            "rail chat side  side"
          `,
        }}
      >
        <div style={{ gridArea: "rail", minHeight: 0, display: "flex" }}>
          <RuntimeRail store={store} />
        </div>
        <div style={{ gridArea: "flow" }}>
          <DataFlowView store={store} />
        </div>
        <div style={{ gridArea: "trace", minHeight: 0, display: "flex" }}>
          <TracePanel store={store} />
        </div>
        <div style={{ gridArea: "chat", minHeight: 0, display: "flex" }}>
          <section className="panel" style={{ flex: 1 }}>
            <header className="panel-header">
              <div className="col" style={{ gap: 2 }}>
                <span className="panel-title">Chat Workspace</span>
                <span className="panel-subtitle">foreground · POST /chat</span>
              </div>
              <div className="panel-actions">
                <span className={`pill ${store.state.loading.chat ? "processing" : "idle"}`}>
                  <span className="dot" />
                  {store.state.loading.chat ? "busy" : "ready"}
                </span>
              </div>
            </header>
            <div className="panel-body" style={{ padding: 0 }}>
              <ChatPanel store={store} />
            </div>
          </section>
        </div>
        <div
          style={{
            gridArea: "side",
            minHeight: 0,
            display: "grid",
            gridTemplateRows: "minmax(0, 1.1fr) minmax(0, 1.4fr) minmax(0, 1fr) minmax(0, 0.9fr)",
            gap: 10,
          }}
        >
          <EventsPanel store={store} />
          <MemoryPanel store={store} />
          <SkillsPanel store={store} />
          <PermissionsPanel store={store} />
        </div>
      </main>
      <footer className="console-footer">
        <span>POST /chat</span>
        <span>POST /background/run-once</span>
        <span className="grow" />
        <span>API base: /api → http://127.0.0.1:8765</span>
      </footer>
    </div>
  );
}

function MobileTabPanel({ tab, store }: { tab: MobileTab; store: ReturnType<typeof useStore> }) {
  switch (tab) {
    case "chat":
      return (
        <section className="panel" style={{ flex: 1 }}>
          <div className="panel-body" style={{ padding: 0 }}>
            <ChatPanel store={store} />
          </div>
        </section>
      );
    case "runtime":
      return (
        <div className="col" style={{ gap: 10, flex: 1 }}>
          <RuntimeRail store={store} />
          <DataFlowView store={store} />
        </div>
      );
    case "events":
      return <EventsPanel store={store} />;
    case "memory":
      return <MemoryPanel store={store} />;
    case "skills":
      return <SkillsPanel store={store} />;
    case "permissions":
      return <PermissionsPanel store={store} />;
    case "trace":
      return <TracePanel store={store} />;
    default:
      return null;
  }
}
