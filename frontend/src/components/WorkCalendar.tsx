import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { listEntries } from "../api/client";
import type { StructuredEntry, StructuredEntryKind } from "../api/types";
import { IconCalendar, IconRefresh } from "./Icons";

type WorkSection =
  | "daily-plan"
  | "daily-review"
  | "phase-plan"
  | "phase-review"
  | "diary"
  | "insight"
  | "feedback";

type WorkCalendarProps = {
  onNavigate: (section: WorkSection) => void;
};

type TooltipState = {
  label: string;
  x: number;
  y: number;
};

const ENTRY_KINDS: StructuredEntryKind[] = [
  "daily_plan",
  "daily_review",
  "phase_plan",
  "phase_review",
  "diary",
  "insight",
  "feedback",
];

const KIND_LABELS: Record<StructuredEntryKind, string> = {
  daily_plan: "每日规划",
  daily_review: "每日复盘",
  phase_plan: "阶段规划",
  phase_review: "阶段复盘",
  diary: "日记",
  insight: "心得 / 体验",
  feedback: "反馈",
};

const KIND_SECTIONS: Record<StructuredEntryKind, WorkSection> = {
  daily_plan: "daily-plan",
  daily_review: "daily-review",
  phase_plan: "phase-plan",
  phase_review: "phase-review",
  diary: "diary",
  insight: "insight",
  feedback: "feedback",
};

const WEEKDAY_LABELS = [
  { row: 1, label: "一" },
  { row: 3, label: "三" },
  { row: 5, label: "五" },
];

function localDateKey(date = new Date()): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function dateFromKey(value: string): Date {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day, 12, 0, 0, 0);
}

function addDays(date: Date, amount: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + amount);
  return next;
}

function startOfWeek(date: Date): Date {
  const next = new Date(date);
  next.setDate(next.getDate() - next.getDay());
  next.setHours(12, 0, 0, 0);
  return next;
}

function sameDay(left: Date, right: Date): boolean {
  return localDateKey(left) === localDateKey(right);
}

function formatCellDate(date: Date): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "short",
  }).format(date);
}

function formatSelectedDate(dateKey: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(dateFromKey(dateKey));
}

function formatEntryTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "已记录";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function entryExcerpt(value: string): string {
  const plain = value.replace(/[#>*_`[\]-]/g, " ").replace(/\s+/g, " ").trim();
  if (!plain) return "这份记录还没有正文";
  return plain.length > 52 ? `${plain.slice(0, 52)}…` : plain;
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) {
    if (error.message.includes("Failed to fetch")) {
      return "暂时无法读取本地记录";
    }
    return error.message;
  }
  return "暂时无法读取本地记录";
}

function activityLevel(count: number): number {
  if (count <= 0) return 0;
  if (count === 1) return 1;
  if (count === 2) return 2;
  if (count <= 4) return 3;
  return 4;
}

export function WorkCalendar({ onNavigate }: WorkCalendarProps) {
  const currentYear = new Date().getFullYear();
  const todayKey = localDateKey();
  const [entries, setEntries] = useState<StructuredEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [year, setYear] = useState(currentYear);
  const [selectedDate, setSelectedDate] = useState(todayKey);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const cellRefs = useRef(new Map<string, HTMLButtonElement>());

  const loadEntries = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const batches = await Promise.all(
        ENTRY_KINDS.map((kind) => listEntries(kind, { limit: 500 })),
      );
      setEntries(batches.flat());
    } catch (reason) {
      setEntries([]);
      setError(errorMessage(reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadEntries();
  }, [loadEntries]);

  useEffect(() => {
    const hideTooltip = () => setTooltip(null);
    window.addEventListener("scroll", hideTooltip, { passive: true });
    return () => window.removeEventListener("scroll", hideTooltip);
  }, []);

  const entriesByDate = useMemo(() => {
    const grouped = new Map<string, StructuredEntry[]>();
    for (const entry of entries) {
      const key = entry.entry_date?.slice(0, 10);
      if (!key) continue;
      const bucket = grouped.get(key) ?? [];
      bucket.push(entry);
      grouped.set(key, bucket);
    }
    for (const bucket of grouped.values()) {
      bucket.sort((left, right) => right.updated_at.localeCompare(left.updated_at));
    }
    return grouped;
  }, [entries]);

  const calendar = useMemo(() => {
    const firstDay = new Date(year, 0, 1, 12, 0, 0, 0);
    const lastDay = new Date(year, 11, 31, 12, 0, 0, 0);
    const gridStart = startOfWeek(firstDay);
    const gridEnd = addDays(startOfWeek(lastDay), 6);
    const columns: Date[][] = [];
    for (let cursor = gridStart; cursor <= gridEnd; cursor = addDays(cursor, 7)) {
      columns.push(Array.from({ length: 7 }, (_, index) => addDays(cursor, index)));
    }
    const allDays = columns.flat();
    const inYearDays = allDays.filter((day) => day.getFullYear() === year);
    const monthLabels: { column: number; label: string }[] = [];
    let previousMonth = -1;
    columns.forEach((week, column) => {
      const firstInYear = week.find((day) => day.getFullYear() === year);
      if (!firstInYear) return;
      const month = firstInYear.getMonth();
      if (month !== previousMonth) {
        monthLabels.push({ column, label: `${month + 1}月` });
        previousMonth = month;
      }
    });
    return { columns, allDays, inYearDays, monthLabels };
  }, [year]);

  const yearEntries = useMemo(
    () => calendar.inYearDays.flatMap((day) => entriesByDate.get(localDateKey(day)) ?? []),
    [calendar.inYearDays, entriesByDate],
  );

  const activeDays = useMemo(
    () => calendar.inYearDays.filter((day) => (entriesByDate.get(localDateKey(day))?.length ?? 0) > 0).length,
    [calendar.inYearDays, entriesByDate],
  );

  const longestStreak = useMemo(() => {
    let longest = 0;
    let current = 0;
    for (const day of calendar.inYearDays) {
      if ((entriesByDate.get(localDateKey(day))?.length ?? 0) > 0) {
        current += 1;
        longest = Math.max(longest, current);
      } else {
        current = 0;
      }
    }
    return longest;
  }, [calendar.inYearDays, entriesByDate]);

  const availableYears = useMemo(() => {
    const years = new Set<number>([currentYear, currentYear - 1]);
    for (const entry of entries) {
      const key = entry.entry_date?.slice(0, 4);
      if (key) years.add(Number(key));
    }
    return Array.from(years).filter(Number.isFinite).sort((left, right) => right - left);
  }, [currentYear, entries]);

  const navigableDays = useMemo(() => {
    const today = dateFromKey(todayKey);
    return calendar.inYearDays.filter((day) => day <= today);
  }, [calendar.inYearDays, todayKey]);

  const selectedEntries = entriesByDate.get(selectedDate) ?? [];
  const selectedKinds = Array.from(new Set(selectedEntries.map((entry) => entry.kind)));

  const chooseYear = (nextYear: number) => {
    setYear(nextYear);
    setSelectedDate(nextYear === currentYear ? todayKey : `${nextYear}-01-01`);
    setTooltip(null);
  };

  const jumpToToday = () => {
    if (year !== currentYear) setYear(currentYear);
    setSelectedDate(todayKey);
    setTooltip(null);
    requestAnimationFrame(() => cellRefs.current.get(todayKey)?.focus());
  };

  const showTooltip = (
    event: { currentTarget: HTMLButtonElement },
    day: Date,
    count: number,
  ) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const label = `${formatCellDate(day)} · ${count ? `${count} 条记录` : "没有记录"}`;
    setTooltip({
      label,
      x: Math.min(window.innerWidth - 84, Math.max(84, rect.left + rect.width / 2)),
      y: Math.max(44, rect.top - 9),
    });
  };

  const handleDayKey = (event: KeyboardEvent<HTMLButtonElement>, dateKey: string) => {
    let delta = 0;
    if (event.key === "ArrowLeft") delta = -7;
    if (event.key === "ArrowRight") delta = 7;
    if (event.key === "ArrowUp") delta = -1;
    if (event.key === "ArrowDown") delta = 1;
    if (event.key === "PageUp") delta = -28;
    if (event.key === "PageDown") delta = 28;
    if (event.key === "Home") {
      const first = navigableDays[0];
      if (!first) return;
      event.preventDefault();
      setSelectedDate(localDateKey(first));
      requestAnimationFrame(() => cellRefs.current.get(localDateKey(first))?.focus());
      return;
    }
    if (event.key === "End") {
      const last = navigableDays[navigableDays.length - 1];
      if (!last) return;
      event.preventDefault();
      setSelectedDate(localDateKey(last));
      requestAnimationFrame(() => cellRefs.current.get(localDateKey(last))?.focus());
      return;
    }
    if (!delta) return;
    const index = navigableDays.findIndex((day) => localDateKey(day) === dateKey);
    const nextDay = navigableDays[index + delta];
    if (!nextDay) return;
    event.preventDefault();
    const nextKey = localDateKey(nextDay);
    setSelectedDate(nextKey);
    requestAnimationFrame(() => cellRefs.current.get(nextKey)?.focus());
  };

  return (
    <section className={`content-card activity-card ${loading ? "is-loading" : ""}`} aria-busy={loading}>
      {tooltip ? (
        <div
          className="activity-tooltip"
          role="tooltip"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          {tooltip.label}
        </div>
      ) : null}

      <div className="card-heading activity-card-heading">
        <div>
          <span className="card-kicker">轨迹 · 工作历</span>
          <h2>每一天，都算数</h2>
          <p className="activity-intro">把零散记录连成一年的轨迹，点击任意日期查看当天留下了什么。</p>
        </div>
        <div className="activity-controls">
          <div className="activity-year-tabs" role="group" aria-label="选择工作历年份">
            {availableYears.slice(0, 3).map((item) => (
              <button
                type="button"
                key={item}
                className={`activity-year-tab ${year === item ? "selected" : ""}`}
                onClick={() => chooseYear(item)}
                aria-pressed={year === item}
              >
                {item}
              </button>
            ))}
          </div>
          {year !== currentYear || selectedDate !== todayKey ? (
            <button type="button" className="activity-today-button" onClick={jumpToToday}>
              回到今天
            </button>
          ) : null}
          <button
            type="button"
            className="activity-icon-button"
            onClick={() => void loadEntries()}
            aria-label="刷新工作历记录"
            title="刷新记录"
            disabled={loading}
          >
            <IconRefresh size={15} />
          </button>
        </div>
      </div>

      <div className="activity-layout">
        <div className="activity-heatmap-panel">
          <div className="activity-metrics" aria-label={`${year} 年记录概览`}>
            <div className="activity-metric">
              <strong>{yearEntries.length}</strong>
              <span>{year} 年记录</span>
            </div>
            <div className="activity-metric">
              <strong>{activeDays}</strong>
              <span>活跃天数</span>
            </div>
            <div className="activity-metric">
              <strong>{longestStreak}</strong>
              <span>最长连续记录</span>
            </div>
            {error ? <div className="activity-error" role="status">{error}</div> : null}
            {!error && loading && entries.length === 0 ? (
              <div className="activity-loading" role="status">正在读取本地轨迹…</div>
            ) : null}
          </div>

          <div className="activity-heatmap-scroll" onScroll={() => setTooltip(null)}>
            <div className="activity-heatmap-canvas">
              <div className="heatmap-month-row" aria-hidden="true">
                <span className="heatmap-axis-spacer" />
                <div
                  className="heatmap-months"
                  style={{ gridTemplateColumns: `repeat(${calendar.columns.length}, var(--activity-cell-size))` }}
                >
                  {calendar.monthLabels.map((item) => (
                    <span key={`${item.column}-${item.label}`} style={{ gridColumnStart: item.column + 1 }}>
                      {item.label}
                    </span>
                  ))}
                </div>
              </div>
              <div className="heatmap-main">
                <div className="heatmap-weekdays" aria-hidden="true">
                  {WEEKDAY_LABELS.map((item) => (
                    <span key={item.label} style={{ gridRowStart: item.row + 1 }}>{item.label}</span>
                  ))}
                </div>
                <div
                  className="heatmap-grid"
                  role="grid"
                  aria-label={`${year} 年 LifeOS 记录热力图`}
                  style={
                    {
                      "--week-count": calendar.columns.length,
                      gridTemplateColumns: `repeat(${calendar.columns.length}, var(--activity-cell-size))`,
                    } as CSSProperties
                  }
                >
                  {calendar.allDays.map((day) => {
                    const key = localDateKey(day);
                    const count = entriesByDate.get(key)?.length ?? 0;
                    const outsideYear = day.getFullYear() !== year;
                    const future = day > dateFromKey(todayKey);
                    if (outsideYear) {
                      return <span key={key} className="activity-cell outside-year" aria-hidden="true" />;
                    }
                    const kinds = Array.from(new Set((entriesByDate.get(key) ?? []).map((entry) => entry.kind)))
                      .map((kind) => KIND_LABELS[kind])
                      .join("、");
                    return (
                      <button
                        type="button"
                        role="gridcell"
                        key={key}
                        ref={(node) => {
                          if (node) cellRefs.current.set(key, node);
                          else cellRefs.current.delete(key);
                        }}
                        className={`activity-cell level-${activityLevel(count)} ${selectedDate === key ? "selected" : ""}`}
                        aria-label={`${formatCellDate(day)}，${count ? `${count} 条记录${kinds ? `：${kinds}` : ""}` : "没有记录"}`}
                        aria-pressed={selectedDate === key}
                        tabIndex={selectedDate === key ? 0 : -1}
                        disabled={future}
                        onClick={() => {
                          setSelectedDate(key);
                          setTooltip(null);
                        }}
                        onKeyDown={(event) => handleDayKey(event, key)}
                        onMouseEnter={(event) => showTooltip(event, day, count)}
                        onMouseLeave={() => setTooltip(null)}
                        onFocus={(event) => showTooltip(event, day, count)}
                        onBlur={() => setTooltip(null)}
                      >
                        <span className="sr-only">{count ? `${count} 条记录` : "没有记录"}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>

          <div className="activity-legend" aria-label="记录数量图例">
            <span>少</span>
            {[0, 1, 2, 3, 4].map((level) => <i key={level} className={`legend-cell level-${level}`} />)}
            <span>多</span>
            <em>悬浮或聚焦查看，点击日期查看详情</em>
          </div>
        </div>

        <aside className="activity-selected-panel" aria-live="polite">
          <div className="activity-selected-head">
            <span className="activity-selected-kicker">选中的一天</span>
            <strong>{formatSelectedDate(selectedDate)}</strong>
            <small>{selectedEntries.length ? `${selectedEntries.length} 条记录` : "还没有记录"}</small>
          </div>

          {selectedEntries.length ? (
            <>
              <div className="activity-kind-list">
                {selectedKinds.map((kind) => (
                  <span key={kind} className={`activity-kind-chip kind-${kind}`}>{KIND_LABELS[kind]}</span>
                ))}
              </div>
              <div className="activity-entry-list">
                {selectedEntries.slice(0, 4).map((entry) => (
                  <button
                    type="button"
                    className="activity-entry"
                    key={entry.id}
                    onClick={() => onNavigate(KIND_SECTIONS[entry.kind])}
                    title={`打开${KIND_LABELS[entry.kind]}`}
                  >
                    <span className={`activity-kind-dot kind-${entry.kind}`} aria-hidden="true" />
                    <span className="activity-entry-copy">
                      <strong>{entry.title || KIND_LABELS[entry.kind]}</strong>
                      <small>{entryExcerpt(entry.content)}</small>
                    </span>
                    <time dateTime={entry.updated_at}>{formatEntryTime(entry.updated_at)}</time>
                  </button>
                ))}
                {selectedEntries.length > 4 ? (
                  <span className="activity-more">还有 {selectedEntries.length - 4} 条记录</span>
                ) : null}
              </div>
            </>
          ) : (
            <div className="activity-empty">
              <span className="activity-empty-icon" aria-hidden="true"><IconCalendar size={18} /></span>
              <p>这一天还没有留下记录。可以从一张简短的计划或一页日记开始。</p>
              <button type="button" className="activity-open-button" onClick={() => onNavigate("daily-plan")}>
                打开每日规划
              </button>
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}
