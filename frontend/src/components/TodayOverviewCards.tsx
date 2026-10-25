import { useEffect, useState } from "react";

const STORAGE_KEY = "lifeos.home.today-tasks.v1";

type TaskDefinition = {
  id: string;
  label: string;
  defaultDone: boolean;
};

const TASKS: TaskDefinition[] = [
  { id: "weekly-goal", label: "写下本周的阶段目标", defaultDone: true },
  { id: "course-reading", label: "完成课程阅读 · 45 分钟", defaultDone: true },
  { id: "project-feedback", label: "整理项目反馈", defaultDone: false },
  { id: "evening-review", label: "晚间复盘", defaultDone: false },
];

type DoneById = Record<string, boolean>;

function todayKey(): string {
  const today = new Date();
  const month = String(today.getMonth() + 1).padStart(2, "0");
  const day = String(today.getDate()).padStart(2, "0");
  return `${today.getFullYear()}-${month}-${day}`;
}

function defaultDone(): DoneById {
  return Object.fromEntries(TASKS.map((task) => [task.id, task.defaultDone]));
}

function loadDone(): DoneById {
  const defaults = defaultDone();
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaults;
    const saved = JSON.parse(raw) as { date?: unknown; done?: unknown } | null;
    if (!saved || saved.date !== todayKey() || !saved.done || typeof saved.done !== "object") {
      return defaults;
    }
    const savedDone = saved.done as Record<string, unknown>;
    return Object.fromEntries(
      TASKS.map((task) => [
        task.id,
        typeof savedDone[task.id] === "boolean" ? savedDone[task.id] : task.defaultDone,
      ]),
    ) as DoneById;
  } catch {
    return defaults;
  }
}

function useTodayTasks() {
  const [doneById, setDoneById] = useState<DoneById>(loadDone);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ date: todayKey(), done: doneById }));
    } catch {
      // 本地存储不可用时仍允许当前会话内勾选。
    }
  }, [doneById]);

  const toggle = (id: string) => {
    setDoneById((current) => ({ ...current, [id]: !current[id] }));
  };

  return { doneById, toggle };
}

function TaskRow({
  label,
  done,
  onToggle,
}: {
  label: string;
  done: boolean;
  onToggle: () => void;
}) {
  return (
    <label className={`task-row ${done ? "task-done" : ""}`}>
      <input
        className="task-check-input"
        type="checkbox"
        checked={done}
        onChange={onToggle}
        aria-label={`${done ? "取消完成" : "完成任务"}：${label}`}
      />
      <span className="task-check" aria-hidden="true">{done ? "✓" : ""}</span>
      <span className="task-label">{label}</span>
      {done ? <small>完成</small> : null}
    </label>
  );
}

export function TodayOverviewCards({ onViewPlan }: { onViewPlan: () => void }) {
  const { doneById, toggle } = useTodayTasks();
  const total = TASKS.length;
  const completed = TASKS.filter((task) => doneById[task.id]).length;
  const remaining = total - completed;
  const progress = `${Math.round((completed / total) * 100)}%`;
  const progressNote = remaining === 0
    ? `已完成 ${completed} 项，今天的安排已经全部完成。`
    : `已完成 ${completed} 项，还有 ${remaining} 项等待你的注意。`;

  return (
    <>
      <section className="content-card progress-card">
        <div className="card-heading">
          <div><span className="card-kicker">今日进度</span><h2>{progress}</h2></div>
          <span className="progress-ring">{completed}/{total}</span>
        </div>
        <div className="progress-track"><span style={{ width: progress }} /></div>
        <p>{progressNote}</p>
        <button className="text-button" onClick={onViewPlan}>查看今日清单 →</button>
      </section>
      <section className="content-card today-card">
        <div className="card-heading">
          <div><span className="card-kicker">接下来</span><h2>今日安排</h2></div>
          <span className="soft-count">{total} 件</span>
        </div>
        {TASKS.map((task) => (
          <TaskRow
            key={task.id}
            label={task.label}
            done={Boolean(doneById[task.id])}
            onToggle={() => toggle(task.id)}
          />
        ))}
      </section>
    </>
  );
}