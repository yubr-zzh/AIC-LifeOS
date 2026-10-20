import type { StructuredEntry } from "../api/types";

function dateLabel(value: string): string {
  const date = new Date(`${value}T12:00:00`);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", weekday: "short" }).format(date);
}

function titleOf(entry: StructuredEntry): string {
  return entry.title.trim() || entry.content.split("\n").find((line) => line.trim())?.replace(/^[#>*\-\d.\s]+/, "").slice(0, 36) || "未命名记录";
}

export function EntryHistory({
  entries,
  activeId,
  onSelect,
  onNew,
  kicker = "历史记录",
  heading = "过去的页面",
  newLabel = "＋ 新建",
}: {
  entries: StructuredEntry[];
  activeId?: string;
  onSelect: (entry: StructuredEntry) => void;
  onNew: () => void;
  kicker?: string;
  heading?: string;
  newLabel?: string;
}) {
  return <aside className="content-card entry-history-card">
    <div className="entry-history-heading">
      <div><span className="card-kicker">{kicker}</span><h3>{heading}</h3></div>
      <button type="button" className="entry-history-new" onClick={onNew} title={newLabel.replace(/^＋\s*/, "")}>{newLabel}</button>
    </div>
    {entries.length === 0 ? <p className="entry-history-empty">还没有保存过记录。</p> : (
      <div className="entry-history-list">
        {entries.map((entry) => <button key={entry.id} type="button"
          className={`entry-history-item ${entry.id === activeId ? "active" : ""}`}
          onClick={() => onSelect(entry)}>
          <span className="entry-history-date">{dateLabel(entry.entry_date)}</span>
          <strong>{titleOf(entry)}</strong>
          <small>{entry.content.replace(/\s+/g, " ").slice(0, 64) || "暂无正文"}</small>
        </button>)}
      </div>
    )}
  </aside>;
}