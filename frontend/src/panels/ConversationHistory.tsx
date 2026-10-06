import { useMemo, useState } from "react";
import type { Conversation, Store } from "../state/store";
import { IconHistory, IconMessage, IconPlus, IconSpark } from "../components/Icons";

interface Props {
  store: Store;
}

type GroupId = "today" | "yesterday" | "week" | "older";

const GROUP_LABELS: { id: GroupId; label: string }[] = [
  { id: "today", label: "今天" },
  { id: "yesterday", label: "昨天" },
  { id: "week", label: "过去 7 天" },
  { id: "older", label: "更早" },
];

function startOfDay(value: Date): number {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
}

function groupFor(iso: string): GroupId {
  const date = new Date(iso);
  const now = new Date();
  const day = 24 * 60 * 60 * 1000;
  const delta = startOfDay(now) - startOfDay(date);
  if (delta <= 0) return "today";
  if (delta === day) return "yesterday";
  if (delta < 7 * day) return "week";
  return "older";
}

function timeLabel(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const group = groupFor(iso);
  if (group === "today") {
    return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(date);
  }
  if (group === "yesterday") return "昨天";
  if (group === "week") {
    return new Intl.DateTimeFormat("zh-CN", { weekday: "short" }).format(date);
  }
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(date);
}

function latestLine(conversation: Conversation): string {
  const latest = [...conversation.messages].reverse().find((message) => message.content.trim());
  if (!latest) return "还没有消息";
  if (latest.decision === "self_plan") return "无需 Agent · 已反馈自规划";
  if (latest.decision === "agent") return "需要 Agent · 等待执行";
  return latest.content.trim().replace(/\s+/g, " ").slice(0, 38);
}

export function ConversationHistory({ store }: Props) {
  const { state, createConversation, selectConversation } = store;
  const [query, setQuery] = useState("");

  const grouped = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const visible = state.conversations
      .filter((conversation) => {
        if (!normalized) return true;
        const searchable = [
          conversation.title,
          ...conversation.messages.map((message) => message.content),
        ].join(" ").toLowerCase();
        return searchable.includes(normalized);
      })
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());

    const map: Record<GroupId, Conversation[]> = {
      today: [],
      yesterday: [],
      week: [],
      older: [],
    };
    for (const conversation of visible) map[groupFor(conversation.updated_at)].push(conversation);
    return map;
  }, [query, state.conversations]);

  return (
    <aside className="conversation-history content-card" aria-label="对话历史">
      <div className="conversation-history-head">
        <div>
          <span className="card-kicker"><IconHistory size={12} /> 历史记录</span>
          <h3>你的对话</h3>
        </div>
        <button
          type="button"
          className="conversation-new-button"
          onClick={() => createConversation()}
          title="新建对话"
          aria-label="新建对话"
        >
          <IconPlus size={14} />
        </button>
      </div>

      <label className="conversation-search">
        <IconMessage size={13} />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索历史记录"
          aria-label="搜索历史记录"
        />
      </label>

      <div className="conversation-history-groups">
        {GROUP_LABELS.map((group) => {
          const items = grouped[group.id];
          if (items.length === 0) return null;
          return (
            <section className="conversation-group" key={group.id}>
              <div className="conversation-group-title">
                <span>{group.label}</span>
                <small>{items.length}</small>
              </div>
              <div className="conversation-group-list">
                {items.map((conversation) => {
                  const active = conversation.id === state.activeConversationId;
                  const selfPlan = conversation.messages.some((message) => message.decision === "self_plan");
                  return (
                    <button
                      type="button"
                      key={conversation.id}
                      className={`conversation-item ${active ? "active" : ""}`}
                      aria-current={active ? "page" : undefined}
                      onClick={() => selectConversation(conversation.id)}
                    >
                      <span className={`conversation-state ${selfPlan ? "self-plan" : ""}`}>
                        <IconSpark size={13} />
                      </span>
                      <span className="conversation-item-copy">
                        <strong>{conversation.title}</strong>
                        <small>{latestLine(conversation)}</small>
                      </span>
                      <span className="conversation-time">{timeLabel(conversation.updated_at)}</span>
                    </button>
                  );
                })}
              </div>
            </section>
          );
        })}
        {Object.values(grouped).every((items) => items.length === 0) ? (
          <div className="conversation-history-empty">没有匹配的历史记录</div>
        ) : null}
      </div>

      <div className="conversation-history-foot">
        <span>按时间自动分组</span>
        <span>{state.conversations.length} 个对话</span>
      </div>
    </aside>
  );
}
