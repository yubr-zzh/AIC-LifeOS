import { useEffect, useMemo, useRef, useState } from "react";
import type { Conversation, Store } from "../state/store";
import { IconClose, IconHistory, IconMessage, IconPlus } from "../components/Icons";

interface Props {
  store: Store;
  mobileOpen?: boolean;
  onClose?: () => void;
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
  const latest = [...conversation.messages].reverse().find((message) => message.content.trim() && !(message.role === "assistant" && message.content.startsWith("LifeOS 已连接。")));
  if (!latest) return "还没有消息";
  if (latest.execution === "pending") return "LifeOS 正在整理回复…";
  if (latest.execution === "error") return "回复暂时没有完成";
  return latest.content.trim().replace(/\s+/g, " ").slice(0, 38);
}

export function ConversationHistory({ store, mobileOpen = false, onClose }: Props) {
  const { state, createConversation, selectConversation } = store;
  const [query, setQuery] = useState("");
  const closeButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (mobileOpen) closeButton.current?.focus();
  }, [mobileOpen]);
  const startConversation = () => {
    setQuery("");
    createConversation();
    onClose?.();
  };

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
    <aside id="conversation-history" className={`conversation-history content-card${mobileOpen ? " mobile-open" : ""}`} aria-label="对话历史" role={mobileOpen ? "dialog" : undefined} aria-modal={mobileOpen || undefined}>
      <div className="conversation-history-head">
        <div>
          <span className="card-kicker"><IconHistory size={12} /> 回到之前的交流</span>
          <h3>最近对话</h3>
        </div>
        <button
          type="button"
          className="conversation-new-button"
          onClick={startConversation}
          title="新建对话"
        >
          <IconPlus size={14} />
          <span>新对话</span>
        </button>
        <button ref={closeButton} type="button" className="conversation-close-button" onClick={onClose} aria-label="关闭历史记录"><IconClose size={16} /></button>
      </div>

      <label className="conversation-search">
        <IconMessage size={13} />
          <input
            type="search"
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
                  return (
                    <button
                      type="button"
                      key={conversation.id}
                      className={`conversation-item ${active ? "active" : ""}`}
                      aria-current={active ? "page" : undefined}
                      onClick={() => { setQuery(""); selectConversation(conversation.id); onClose?.(); }}
                    >
                      <span className="conversation-state">
                        <IconMessage size={14} />
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
          <div className="conversation-history-empty">没有找到相关对话。试试其他关键词，或开始一段新对话。</div>
        ) : null}
      </div>

      <div className="conversation-history-foot">按最近交流时间排列</div>
    </aside>
  );
}
