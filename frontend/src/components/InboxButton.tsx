import { useMemo, useState } from "react";
import type { AgentStore } from "../state/agentStore";
import { IconInbox } from "./Icons";

interface InboxItem {
  id: string;
  title: string;
  detail: string;
  tone: "attention" | "done" | "error";
  at: number;
}

const READ_KEY = "lifeos.inbox.read.v1";

function loadRead(): Set<string> {
  try {
    const raw = localStorage.getItem(READ_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? parsed.map(String) : []);
  } catch {
    return new Set();
  }
}

function saveRead(ids: Set<string>): void {
  try { localStorage.setItem(READ_KEY, JSON.stringify([...ids])); } catch { /* local preference */ }
}

export function InboxButton({ agent, onOpenAgent }: { agent: AgentStore; onOpenAgent: () => void }) {
  const [open, setOpen] = useState(false);
  const [read, setRead] = useState<Set<string>>(loadRead);

  const items = useMemo(() => {
    const rows: InboxItem[] = [];
    for (const request of Object.values(agent.state.pending)) {
      if (agent.state.resolved[request.requestId]) continue;
      rows.push({
        id: `permission:${request.requestId}`,
        title: "Agent 正在等待你的确认",
        detail: `${request.toolName} · ${request.title || request.displayName}`,
        tone: "attention",
        at: request.createdAt,
      });
    }
    for (const question of Object.values(agent.state.questions)) {
      if (agent.state.questionClosed[question.questionId]) continue;
      rows.push({
        id: `question:${question.questionId}`,
        title: "Agent 有问题需要你回答",
        detail: question.questions.map((item) => item.question).join(" / "),
        tone: "attention",
        at: question.createdAt,
      });
    }
    for (const [sessionId, result] of Object.entries(agent.state.lastResult)) {
      rows.push({
        id: `result:${sessionId}:${result.batchDone}`,
        title: result.isError ? "Agent 任务未完成" : "Agent 任务已完成",
        detail: `会话 ${sessionId.slice(0, 8)} · 第 ${result.batchDone}/${result.batchTotal || "?"} 条`,
        tone: result.isError ? "error" : "done",
        at: Date.now(),
      });
    }
    return rows.sort((a, b) => (a.tone === "attention" ? -1 : 1) - (b.tone === "attention" ? -1 : 1) || b.at - a.at).slice(0, 12);
  }, [agent.state.lastResult, agent.state.pending, agent.state.questionClosed, agent.state.questions, agent.state.resolved]);

  const unread = items.filter((item) => !read.has(item.id)).length;

  const markRead = (ids: string[]) => {
    setRead((current) => {
      const next = new Set(current);
      ids.forEach((id) => next.add(id));
      saveRead(next);
      return next;
    });
  };

  return <div className="inbox-wrap">
    <button className="header-icon-button inbox-button" onClick={() => setOpen((value) => !value)}
      title="Inbox · Agent 任务进展" aria-label={`Inbox，${unread} 条未读`} aria-expanded={open}>
      <IconInbox size={16} />
      {unread > 0 ? <span className="inbox-badge">{unread > 9 ? "9+" : unread}</span> : null}
    </button>
    {open ? <div className="inbox-popover">
      <div className="inbox-heading">
        <div><span className="card-kicker">INBOX</span><h3>Agent 进展</h3></div>
        <button type="button" className="text-button" onClick={() => markRead(items.map((item) => item.id))} disabled={items.length === 0}>全部已读</button>
      </div>
      {items.length === 0 ? <p className="inbox-empty">暂时没有新的 Agent 通知。</p> : <div className="inbox-list">
        {items.map((item) => <button key={item.id} type="button" className={`inbox-item ${item.tone} ${read.has(item.id) ? "read" : "unread"}`}
          onClick={() => { markRead([item.id]); setOpen(false); onOpenAgent(); }}>
          <span className="inbox-dot" />
          <span><strong>{item.title}</strong><small>{item.detail}</small></span>
        </button>)}
      </div>}
      <p className="inbox-foot">外部 Agent 的邮件通道待后端接入；当前先展示本机 Agent 的完成与待确认状态。</p>
    </div> : null}
  </div>;
}