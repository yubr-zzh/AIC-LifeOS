import { useCallback, useEffect, useMemo, useState } from "react";
import { listEntries } from "../api/client";
import type { StructuredEntry, StructuredEntryKind } from "../api/types";

type WorkSection = "daily-plan" | "daily-review" | "phase-plan" | "phase-review" | "diary" | "insight" | "feedback";

const kinds: StructuredEntryKind[] = ["daily_plan", "daily_review", "phase_plan", "phase_review", "diary", "insight", "feedback"];
const kindLabel: Record<StructuredEntryKind, string> = {
  daily_plan: "每日规划", daily_review: "每日复盘", phase_plan: "阶段规划",
  phase_review: "阶段复盘", diary: "日记", insight: "心得 / 体验", feedback: "反馈",
};
const targetSection: Record<StructuredEntryKind, WorkSection> = {
  daily_plan: "daily-plan", daily_review: "daily-review", phase_plan: "phase-plan",
  phase_review: "phase-review", diary: "diary", insight: "insight", feedback: "feedback",
};

function dateKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function localDate(key: string): Date {
  const [year, month, day] = key.split("-").map(Number);
  return new Date(year, month - 1, day, 12);
}

export function WorkCalendar({ onNavigate }: { onNavigate: (section: WorkSection) => void }) {
  const today = dateKey(new Date());
  const [year, setYear] = useState(new Date().getFullYear());
  const [selected, setSelected] = useState(today);
  const [entries, setEntries] = useState<StructuredEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const pages = await Promise.all(kinds.map((kind) => listEntries(kind)));
      setEntries(pages.flat());
    } catch {
      setError("暂时无法读取结构化记录，请确认 LifeOS 服务正在运行后重试。");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const byDate = useMemo(() => {
    const result = new Map<string, StructuredEntry[]>();
    for (const entry of entries) {
      const key = entry.entry_date.slice(0, 10);
      const bucket = result.get(key) ?? [];
      bucket.push(entry);
      result.set(key, bucket);
    }
    return result;
  }, [entries]);

  const days = useMemo(() => {
    const first = new Date(year, 0, 1, 12);
    const offset = (first.getDay() + 6) % 7;
    const total = (Date.UTC(year + 1, 0, 1) - Date.UTC(year, 0, 1)) / 86_400_000;
    return [
      ...Array.from({ length: offset }, () => null),
      ...Array.from({ length: total }, (_, index) => new Date(year, 0, index + 1, 12)),
    ];
  }, [year]);

  const yearRecords = entries.filter((entry) => entry.entry_date.startsWith(`${year}-`));
  const activeDays = new Set(yearRecords.map((entry) => entry.entry_date.slice(0, 10))).size;
  const selectedEntries = byDate.get(selected) ?? [];

  const changeYear = (next: number) => {
    setYear(next);
    setSelected(next === new Date().getFullYear() ? today : `${next}-01-01`);
  };

  return (
    <section className="content-card activity-card" aria-busy={loading}>
      <header className="activity-heading">
        <div><span className="card-kicker">记录 · 工作历</span><h2>把日常记录连成轨迹</h2>
          <p>这里只汇总 LifeOS 已保存的规划、复盘、日记与心得，不会创建或修改记录。</p></div>
        <div className="activity-actions">
          <label>年份<select value={year} onChange={(event) => changeYear(Number(event.target.value))}>
            {[new Date().getFullYear() - 2, new Date().getFullYear() - 1, new Date().getFullYear()].map((value) => <option key={value}>{value}</option>)}
          </select></label>
          <button type="button" className="subtle-button" onClick={() => void load()} disabled={loading}>刷新</button>
        </div>
      </header>

      <div className="activity-summary"><strong>{yearRecords.length}</strong><span>{year} 年记录</span><strong>{activeDays}</strong><span>有记录的日子</span>
        {loading ? <span role="status">正在读取…</span> : null}{error ? <span className="activity-error" role="alert">{error}</span> : null}
      </div>

      <div className="activity-calendar" role="group" aria-label={`${year} 年工作历`}>
        {days.map((day, index) => {
          if (!day) return <span aria-hidden="true" className="activity-day-blank" key={`blank-${index}`} />;
          const key = dateKey(day);
          const count = byDate.get(key)?.length ?? 0;
          const level = count === 0 ? 0 : count === 1 ? 1 : count <= 3 ? 2 : count <= 5 ? 3 : 4;
          return <button key={key} type="button" className={`activity-day level-${level} ${selected === key ? "selected" : ""}`}
            aria-label={`${key}，${count} 条记录`} aria-pressed={selected === key} onClick={() => setSelected(key)} title={`${key} · ${count} 条记录`} />;
        })}
      </div>
      <div className="activity-legend"><span>少</span>{[0, 1, 2, 3, 4].map((level) => <i key={level} className={`activity-day level-${level}`} />)}<span>多</span></div>

      <section className="activity-day-panel" aria-live="polite">
        <div className="activity-day-heading"><div><span className="card-kicker">选中日期</span><h3>{new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", weekday: "long" }).format(localDate(selected))}</h3></div>
          <button type="button" className="text-button" onClick={() => { setYear(new Date().getFullYear()); setSelected(today); }}>回到今天</button></div>
        {selectedEntries.length === 0 ? <p className="activity-empty">这一天还没有保存的结构化记录。</p> : (
          <ul className="activity-entry-list">{selectedEntries.map((entry) => <li key={entry.id}>
            <div><span className="activity-kind">{kindLabel[entry.kind]}</span><strong>{entry.title || kindLabel[entry.kind]}</strong>
              <p>{entry.content.replace(/\s+/g, " ").slice(0, 150) || "暂无正文"}</p></div>
            <button type="button" className="text-button" onClick={() => onNavigate(targetSection[entry.kind])}>打开记录 →</button>
          </li>)}</ul>
        )}
      </section>
    </section>
  );
}
