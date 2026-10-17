import { useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "./state/store";
import { useAgentStore } from "./state/agentStore";
import { useAgentStream } from "./hooks/useAgentStream";
import { listEntries, proposeEntryMemoryCandidate, saveEntry } from "./api/client";
import type { MemoryScope, StructuredEntry, StructuredEntryKind } from "./api/types";
import { RichEditor } from "./components/RichEditor";
import { ChatPanel } from "./panels/ChatPanel";
import { AgentsSection } from "./panels/AgentsSection";
import { RuntimeRail } from "./panels/RuntimeRail";
import { EventsPanel } from "./panels/EventsPanel";
import { MemoryPanel } from "./panels/MemoryPanel";
import { TracePanel } from "./panels/TracePanel";
import { SkillsPanel } from "./panels/SkillsPanel";
import { PermissionsPanel } from "./panels/PermissionsPanel";
import { DataFlowView } from "./panels/DataFlowView";
import { SettingsPage } from "./panels/SettingsPage";
import { WorkCalendar } from "./components/WorkCalendar";
import {
  IconArrowRight,
  IconBook,
  IconBolt,
  IconCalendar,
  IconCheck,
  IconCircleDot,
  IconHome,
  IconInbox,
  IconLeaf,
  IconMessage,
  IconPlus,
  IconSettings,
  IconSpark,
  IconSun,
  IconTrash,
} from "./components/Icons";

type SectionId =
  | "home"
  | "calendar"
  | "daily-plan"
  | "daily-review"
  | "phase-plan"
  | "phase-review"
  | "chat"
  | "agents"
  | "feedback"
  | "diary"
  | "insight"
  | "memory"
  | "settings";

type NavIcon = "home" | "message" | "calendar" | "book" | "spark" | "bolt";
const navigation: { group: string; items: { id: SectionId; label: string; icon: NavIcon; hint?: string }[] }[] = [
  {
    group: "工作台",
    items: [
      { id: "home", label: "今日概览", icon: "home" },
      { id: "chat", label: "对话", icon: "message", hint: "与 LifeOS 对话" },
      { id: "agents", label: "本地 Agent", icon: "bolt", hint: "发现、连接、运行本机 Agent" },
    ],
  },
  {
    group: "计划与复盘",
    items: [
      { id: "daily-plan", label: "每日规划", icon: "calendar", hint: "安排今天" },
      { id: "daily-review", label: "每日复盘", icon: "spark", hint: "收束今天" },
      { id: "phase-plan", label: "阶段性规划", icon: "calendar", hint: "看长期方向" },
      { id: "phase-review", label: "阶段性复盘", icon: "spark", hint: "校准路径" },
      { id: "diary", label: "日记", icon: "book", hint: "留住今天" },
      { id: "insight", label: "心得 / 体验", icon: "spark", hint: "沉淀感受" },
    ],
  },
  {
    group: "反馈与记忆",
    items: [{ id: "feedback", label: "反馈", icon: "message", hint: "留下你的声音" }],
  },
  {
    group: "记录",
    items: [{ id: "calendar", label: "工作历", icon: "calendar", hint: "回看每日记录" }],
  },
];

const sectionTitle: Record<SectionId, string> = {
  home: "今天",
  chat: "对话",
  agents: "本地 Agent",
  "daily-plan": "每日规划",
  "daily-review": "每日复盘",
  "phase-plan": "阶段性规划",
  "phase-review": "阶段性复盘",
  feedback: "反馈",
  diary: "日记",
  insight: "心得 / 体验",
  calendar: "工作历",
  memory: "Memory",
  settings: "设置",
};

function NavIconGlyph({ name }: { name: NavIcon }) {
  if (name === "home") return <IconHome size={17} />;
  if (name === "message") return <IconMessage size={17} />;
  if (name === "calendar") return <IconCalendar size={17} />;
  if (name === "book") return <IconBook size={17} />;
  if (name === "bolt") return <IconBolt size={17} />;
  return <IconSpark size={17} />;
}

export default function App() {
  const store = useStore();
  const agent = useAgentStore();
  const api = useAgentStream(agent);
  const initialSection: SectionId = (() => {
    if (typeof window === "undefined") return "home";
    const hash = window.location.hash.replace(/^#\/?/, "");
    return (hash as SectionId) || "home";
  })();
  const [active, setActive] = useState<SectionId>(initialSection);
  const [dark, setDark] = useState(false);
  const [inboxOpen, setInboxOpen] = useState(false);
  const todayLabel = useMemo(() => {
    const fmt = new Intl.DateTimeFormat("zh-CN", { weekday: "long", month: "long", day: "numeric" });
    return fmt.format(new Date());
  }, []);

  // 7.7.1 决策回路的前端落点：Agent 每条指令的结果以独立一条消息回到左栏。
  // agentStore 不能反向 import 主 store，所以由同时持有两者的这一层搭桥。
  // 用 ref 记住已领走的 seq —— 依赖里放 report 对象会让每次 result 帧都重跑，
  // 而同一批里会有多条 result。
  const yiLing = useRef(0);
  const bao = agent.state.report;
  useEffect(() => {
    if (!bao || bao.seq <= yiLing.current) return;
    yiLing.current = bao.seq;
    store.dispatch({ type: "APPEND_AGENT_SUMMARY", text: bao.title, traceId: bao.traceId });
  }, [bao, store]);

  const select = (id: SectionId) => {
    setActive(id);
    setInboxOpen(false);
    if (typeof window !== "undefined") window.location.hash = `#/${id}`;
  };

  return (
    <div className={`lifeos-shell ${dark ? "theme-night" : ""}`}>
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <aside className="side-nav">
        <div className="brand-block">
          <div className="brand-mark"><IconBolt size={17} /></div>
          <div>
            <div className="brand-name">LifeOS</div>
            <div className="brand-caption">你的个人操作系统</div>
          </div>
        </div>

        <nav className="main-nav" aria-label="主导航">
          {navigation.map((group) => (
            <div className="nav-group" key={group.group}>
              <div className="nav-group-title">{group.group}</div>
              {group.items.map((item) => (
                <button
                  key={item.id}
                  className={`nav-item ${active === item.id ? "active" : ""}`}
                  onClick={() => select(item.id)}
                  aria-current={active === item.id ? "page" : undefined}
                  title={item.hint}
                >
                  <span className="nav-icon" aria-hidden="true"><NavIconGlyph name={item.icon} /></span>
                  <span className="nav-label">{item.label}</span>
                  {item.id === "agents" && agent.todo > 0 ? (
                    <span className="nav-badge" title={`${agent.todo} 项等你决定`}>{agent.todo}</span>
                  ) : null}
                  {item.id === "daily-review" ? <span className="nav-dot" /> : null}
                </button>
              ))}
            </div>
          ))}
        </nav>

        <div className="side-footer">
          <div className="side-footer-line"><span className="status-orb" />系统运行良好</div>
          <div className="side-footer-sub">本地工作区 · 数据已同步</div>
        </div>
        <div className="dev-footer">
          <button className="dev-footer-link" onClick={() => select("memory")} title="Memory 候选 / 生命周期 / 撤回 / 画像">
            <IconSpark size={11} /> Memory
          </button>
        </div>
      </aside>

      <div className="content-shell">
        <header className="workspace-header">
          <div className="workspace-date">{todayLabel}</div>
          <div className="header-actions">
            <span className="sync-label"><span className="status-orb" />刚刚同步</span>
            <button
              className={`header-icon-button ${inboxOpen ? "is-active" : ""}`}
              onClick={() => setInboxOpen(!inboxOpen)}
              title="收件箱"
              aria-label="收件箱"
              aria-expanded={inboxOpen}
            >
              <IconInbox size={16} />
            </button>
            <button
              className="header-icon-button"
              onClick={() => setDark(!dark)}
              title="切换主题"
              aria-label={`切换到${dark ? "浅色" : "夜间"}主题`}
              aria-pressed={dark}
            >
              {dark ? <IconSun size={16} /> : <IconSpark size={16} />}
            </button>
            <button
              className="header-icon-button"
              onClick={() => select("settings")}
              title="设置"
              aria-label="设置"
              aria-expanded={active === "settings"}
            >
              <IconSettings size={16} />
            </button>
            <div className="avatar">Z</div>
          </div>
          {inboxOpen ? <InboxPopover onClose={() => setInboxOpen(false)} /> : null}
        </header>

        <main id="main-content" className="workspace-main">
          <div className={`page-title-row ${active === "chat" ? "page-title-row-chat" : ""}`}>
            <h1 className="page-title">{sectionTitle[active]}</h1>
          </div>
          <SectionContent
            active={active}
            store={store}
            agent={agent}
            api={api}
            onNavigate={select}
            dark={dark}
            onDarkChange={setDark}
            onOpenInbox={() => setInboxOpen(true)}
          />
        </main>
      </div>
    </div>
  );
}

function InboxPopover({ onClose }: { onClose: () => void }) {
  return (
    <div className="inbox-popover" role="dialog" aria-label="收件箱">
      <div className="inbox-head">
        <strong>收件箱</strong>
        <button className="header-icon-button" onClick={onClose} aria-label="关闭" title="关闭">×</button>
      </div>
      <div className="inbox-empty">
        <span className="inbox-empty-icon" aria-hidden="true"><IconInbox size={28} /></span>
        <p>还没有外部 Agent 的任务消息。</p>
        <small>当本机 Agent 完成任务或需要你确认时，通知会出现在这里。</small>
      </div>
    </div>
  );
}

function SectionContent({
  active,
  store,
  agent,
  api,
  onNavigate,
  dark,
  onDarkChange,
  onOpenInbox,
}: {
  active: SectionId;
  store: ReturnType<typeof useStore>;
  agent: ReturnType<typeof useAgentStore>;
  api: ReturnType<typeof useAgentStream>;
  onNavigate: (id: SectionId) => void;
  dark: boolean;
  onDarkChange: (dark: boolean) => void;
  onOpenInbox: () => void;
}) {
  if (active === "chat") {
    // 对话整页：直接占满主区，不再套 content-card（Impeccable 黑名单：卡片当容器）。
    return (
      <div className="chat-host">
        <ChatPanel store={store} agent={agent} api={api} />
      </div>
    );
  }
  if (active === "agents") return <AgentsSection store={agent} api={api} onGoChat={() => onNavigate("chat")} />;
  if (active === "feedback") return <FeedbackPage />;
  if (active === "diary") return <DiaryPage />;
  if (active === "calendar") return <WorkCalendar onNavigate={onNavigate} />;
  if (active === "insight") return <InsightPage />;
  if (active === "memory") return <MemoryPage store={store} />;
  if (active === "settings") return <SettingsPage dark={dark} onDarkChange={onDarkChange} />;
  if (active === "daily-review" || active === "phase-review") return <ReviewPage phase={active === "phase-review"} store={store} />;
  if (active === "daily-plan" || active === "phase-plan") return <PlanningPage phase={active === "phase-plan"} store={store} />;
  return <HomePage store={store} onNavigate={onNavigate} />;
}

const DAILY_REMINDERS: string[] = [
  "把最重要的事放在最前面；其余的，会自己找到位置。",
  "慢一点，但要向前。",
  "今天的一页空白，也是一种完成。",
  "选择做一件事，比做完十件事更难，也更值。",
  "完成好过完美。",
  "留一点余地给意外的好事。",
  "你不需要把每件事都做好；你只需要知道此刻什么值得被做好。",
  "想不清楚的时候，先动起来。",
  "记下来，未来会谢你。",
  "今天的复盘，是明天的计划。",
  "不必塞满日程；重要的那件，先做。",
  "用笔尖慢下来，思绪会清楚。",
  "判断你的不是今天做了什么，而是今天没做什么。",
  "放下和坚持一样重要。",
  "在精力最好的时候，做最难的事。",
  "少即是多，慢即是快。",
  "把目标写下来，可见的进度才有意义。",
  "今天你为未来留下的，比你为今天做的，更值得被记住。",
  "犹豫是数据不够。去查，去问，去做最小的一步。",
  "把时间花在让你成为自己的事情上。",
];

function dayOfYearIndex(total: number): number {
  const now = new Date();
  const start = new Date(now.getFullYear(), 0, 0);
  const diff = now.getTime() - start.getTime();
  const day = Math.floor(diff / (1000 * 60 * 60 * 24));
  return day % total;
}

const DEFAULT_TODAY_TASKS = [
  "写下本周的阶段目标",
  "完成课程阅读 · 45 分钟",
  "整理项目反馈",
  "晚间复盘",
];

const TASK_KEY = "lifeos.home.todayTasks.v1";

function loadTodayTasks(): { label: string; done: boolean }[] {
  if (typeof localStorage === "undefined") return DEFAULT_TODAY_TASKS.map((label) => ({ label, done: false }));
  try {
    const raw = localStorage.getItem(TASK_KEY);
    if (!raw) return DEFAULT_TODAY_TASKS.map((label) => ({ label, done: false }));
    const parsed = JSON.parse(raw) as { label: string; done: boolean }[];
    if (!Array.isArray(parsed)) throw new Error("bad shape");
    return parsed;
  } catch {
    return DEFAULT_TODAY_TASKS.map((label) => ({ label, done: false }));
  }
}

function HomePage({ store, onNavigate }: { store: ReturnType<typeof useStore>; onNavigate: (id: SectionId) => void }) {
  const [tasks, setTasks] = useState(() => loadTodayTasks());
  useEffect(() => {
    if (typeof localStorage !== "undefined") localStorage.setItem(TASK_KEY, JSON.stringify(tasks));
  }, [tasks]);
  const completed = tasks.filter((t) => t.done).length;
  const total = tasks.length;
  const progressPct = total ? Math.round((completed / total) * 100) : 0;
  const today = new Intl.DateTimeFormat("zh-CN", { weekday: "long", month: "long", day: "numeric" }).format(new Date());
  const reminder = DAILY_REMINDERS[dayOfYearIndex(DAILY_REMINDERS.length)];

  const toggleTask = (idx: number) => {
    setTasks((current) => current.map((t, i) => (i === idx ? { ...t, done: !t.done } : t)));
  };
  const addTask = (label: string) => {
    if (!label.trim()) return;
    setTasks((current) => [...current, { label: label.trim(), done: false }]);
  };
  const [draft, setDraft] = useState("");
  return (
    <div className="home-grid">
      <section className="home-hero">
        <div className="home-hero-meta">{today}</div>
        <h2 className="home-hero-title">慢一点，但要向前。</h2>
        <p className="home-hero-lead">今天适合完成一件需要专注的事，也适合给自己留一点空白。</p>
        <div className="home-hero-actions">
          <button className="green-button" onClick={() => onNavigate("daily-plan")}>
            开始今日规划
            <IconArrowRight size={14} />
          </button>
          <button className="text-button" onClick={() => onNavigate("diary")}>
            写一篇日记
          </button>
        </div>
      </section>

      <section className="home-today content-card">
        <header className="block-head">
          <span className="block-kicker">接下来</span>
          <span className="block-meta">{completed}/{total} 完成</span>
        </header>
        <ul className="home-task-list" role="list">
          {tasks.map((task, idx) => (
            <li key={`${task.label}-${idx}`} className={task.done ? "is-done" : ""}>
              <button
                className="check-box"
                role="checkbox"
                aria-checked={task.done}
                aria-label={task.label}
                onClick={() => toggleTask(idx)}
              >
                {task.done ? <IconCheck size={12} /> : null}
              </button>
              <span className="home-task-label">{task.label}</span>
            </li>
          ))}
        </ul>
        <form
          className="home-task-add"
          onSubmit={(event) => {
            event.preventDefault();
            addTask(draft);
            setDraft("");
          }}
        >
          <input
            type="text"
            placeholder="再加一件小事…"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            aria-label="添加今日任务"
          />
          <button type="submit" className="ghost" disabled={!draft.trim()}>
            <IconPlus size={12} /> 添加
          </button>
        </form>
        <div className="home-progress" aria-hidden="true">
          <div className="home-progress-track">
            <span style={{ width: `${progressPct}%` }} />
          </div>
          <small>{progressPct}%</small>
        </div>
      </section>

      <aside className="home-reminder content-card">
        <span className="block-kicker">今日提醒</span>
        <blockquote>{reminder}</blockquote>
        <small>每天一句 · 一年不重样</small>
      </aside>

      <section className="home-rhythm content-card">
        <header className="block-head">
          <span className="block-kicker">生活节奏</span>
          <span className="block-meta">本周 4 / 7 天</span>
        </header>
        <p className="home-rhythm-copy">持续前进不一定要很用力。今天完成重要的事，也记得给自己一点休息。</p>
        <div className="week-dots" aria-hidden="true">
          <span className="filled" />
          <span className="filled" />
          <span className="filled" />
          <span className="filled" />
          <span />
          <span />
          <span />
        </div>
        <button className="text-button" onClick={() => onNavigate("calendar")}>
          查看工作历
        </button>
      </section>

      <section className="home-agents content-card">
        <header className="block-head">
          <span className="block-kicker">本地 Agent</span>
          <span className="block-meta">空闲 · 等待任务</span>
        </header>
        <p className="home-agents-copy">把执行交给机器上的 Agent，审批始终由你点。</p>
        <button className="text-button" onClick={() => onNavigate("agents")}>
          打开 Agent 面板
        </button>
      </section>
    </div>
  );
}

function useEntryDraft(kind: StructuredEntryKind, initial: { title?: string; content?: string }) {
  const [id, setId] = useState<string>();
  const [title, setTitle] = useState(initial.title ?? "");
  const [content, setContent] = useState(initial.content ?? "");
  const [mood, setMood] = useState<string | null>(null);
  const [metadata, setMetadata] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [entries, setEntries] = useState<StructuredEntry[]>([]);

  const refresh = () => listEntries(kind).then(setEntries).catch(() => setEntries([]));

  useEffect(() => {
    let alive = true;
    listEntries(kind).then((items) => {
      if (!alive) return;
      setEntries(items);
      const first = items[0];
      if (!first) { setLoaded(true); return; }
      setId(first.id); setTitle(first.title); setContent(first.content);
      setMood(first.mood ?? null); setMetadata(first.metadata ?? {}); setLoaded(true);
    }).catch(() => { if (alive) setLoaded(true); });
    return () => { alive = false; };
  }, [kind]);

  const save = async (overrides: Partial<{ title: string; content: string; mood: string | null; metadata: Record<string, unknown> }> = {}) => {
    setSaving(true);
    try {
      const entry = await saveEntry({ id, kind, entry_date: new Date().toISOString().slice(0, 10), title: overrides.title ?? title, content: overrides.content ?? content, mood: overrides.mood ?? mood, metadata: overrides.metadata ?? metadata });
      setId(entry.id); setTitle(entry.title); setContent(entry.content); setMood(entry.mood ?? null); setMetadata(entry.metadata ?? {});
      await refresh();
    } finally { setSaving(false); }
  };
  return { id, title, setTitle, content, setContent, mood, setMood, metadata, setMetadata, saving, loaded, save, entries, refresh };
}

function PlanningPage({ phase, store }: { phase: boolean; store: ReturnType<typeof useStore> }) {
  const draft = useEntryDraft(phase ? "phase_plan" : "daily_plan", { content: phase ? "建立一个更稳定的学习与创作节奏。" : "" });
  return (
    <div className="planning-layout">
      <section className="content-card editor-card">
        <div className="block-head">
          <h2 className="editor-card-title">{phase ? "未来 90 天，我想靠近什么？" : "今天最值得推进的三件事"}</h2>
          <span className="block-meta">{draft.loaded ? (draft.id ? "已保存" : "新规划") : "读取中"}</span>
        </div>
        <RichEditor
          value={draft.content}
          onChange={draft.setContent}
          placeholder={phase ? "写下这个阶段最想完成、体验或改变的事情…" : "从最重要的事情开始，不必一次写完…"}
          ariaLabel={phase ? "阶段性规划" : "今日规划"}
        />
        <div className="editor-footer">
          <span>内容会保存到本地 SQLite</span>
          <button className="green-button" onClick={() => void draft.save()} disabled={draft.saving}>
            {draft.saving ? "保存中…" : "保存规划"}
            <IconArrowRight size={14} />
          </button>
        </div>
        {draft.id ? <MemoryCaptureForm entryId={draft.id} phase={phase} store={store} /> : null}
      </section>
      <aside className="content-card side-tip">
        <h3>{phase ? "目标需要方向，也需要边界。" : "计划不是待办事项的堆叠。"}</h3>
        <p>{phase ? "试着写清楚：这件事为什么现在重要？完成之后，你希望自己处于什么状态？" : "如果今天只能做一件事，它会是什么？先把这一件事放在最前面。"}</p>
      </aside>
    </div>
  );
}

function ReviewPage({ phase, store }: { phase: boolean; store: ReturnType<typeof useStore> }) {
  const draft = useEntryDraft(phase ? "phase_review" : "daily_review", {});
  const [checks, setChecks] = useState<{ id: string; label: string; done: boolean }[]>([]);
  const [newCheck, setNewCheck] = useState("");

  // 每日复盘时拉取"今日规划"作为勾选清单来源；阶段性复盘不做这个。
  useEffect(() => {
    if (phase) return;
    let alive = true;
    listEntries("daily_plan").then((items) => {
      if (!alive) return;
      const today = new Date().toISOString().slice(0, 10);
      const todayEntry = items.find((it) => it.entry_date === today) ?? items[0];
      if (!todayEntry) { setChecks([]); return; }
      // 简单解析：把规划正文按行切，每行一项。
      const lines = todayEntry.content
        .split(/\r?\n/)
        .map((line) => line.replace(/^[-*•·\s]+/, "").trim())
        .filter((line) => line.length > 0);
      const saved: { id: string; label: string; done: boolean }[] = (Array.isArray(draft.metadata.checks) ? draft.metadata.checks : []) as { id: string; label: string; done: boolean }[];
      setChecks(
        lines.length > 0
          ? lines.map((label, i) => ({
              id: `plan-${i}`,
              label,
              done: saved.find((s) => s.label === label)?.done ?? false,
            }))
          : saved,
      );
    }).catch(() => setChecks([]));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, draft.id]);

  const toggleCheck = (id: string) => {
    setChecks((current) => current.map((c) => (c.id === id ? { ...c, done: !c.done } : c)));
  };
  const addCheck = () => {
    const label = newCheck.trim();
    if (!label) return;
    setChecks((current) => [...current, { id: `adhoc-${Date.now()}`, label, done: false }]);
    setNewCheck("");
  };

  const save = () =>
    void draft.save({
      content: JSON.stringify({ checks, editorHtml: draft.content }),
      metadata: { checks },
    });

  return (
    <div className="review-layout">
      <section className="content-card review-prompts">
        <div className="block-head">
          <h2 className="editor-card-title">{phase ? "回看这段路，你发现了什么？" : "今天发生了什么？"}</h2>
          <span className="block-meta">{draft.id ? "已保存" : "未完成"}</span>
        </div>

        {!phase ? (
          <>
            <span className="review-section-title">从今日规划里勾选完成度</span>
            {checks.length > 0 ? (
              <ul className="review-checks" role="list">
                {checks.map((c) => (
                  <li key={c.id} className={c.done ? "is-done" : ""}>
                    <button
                      className="check-box"
                      role="checkbox"
                      aria-checked={c.done}
                      aria-label={c.label}
                      onClick={() => toggleCheck(c.id)}
                    >
                      {c.done ? <IconCheck size={12} /> : null}
                    </button>
                    <span className="review-check-label">{c.label}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="review-checks-empty">今天还没有写过规划。</p>
            )}
            <div className="review-check-add">
              <input
                type="text"
                placeholder="额外做了 / 没做的事…"
                value={newCheck}
                onChange={(event) => setNewCheck(event.target.value)}
                onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addCheck(); } }}
                aria-label="添加复盘条目"
              />
              <button type="button" className="ghost" onClick={addCheck} disabled={!newCheck.trim()}>
                <IconPlus size={12} /> 添加
              </button>
            </div>
          </>
        ) : null}

        <span className="review-section-title">{phase ? "阶段心得" : "写下今天真正发生了什么"}</span>
        <RichEditor
          value={draft.content}
          onChange={draft.setContent}
          placeholder={phase ? "回看这段路，你发现了什么…" : "诚实，但不要苛刻。"}
          minHeight={220}
          ariaLabel={phase ? "阶段性复盘正文" : "每日复盘正文"}
        />
        <div className="editor-footer">
          <span>内容会保存到本地 SQLite</span>
          <button className="green-button" onClick={save} disabled={draft.saving}>
            {draft.saving ? "保存中…" : "完成复盘"}
            <IconArrowRight size={14} />
          </button>
        </div>
        {draft.id ? <MemoryCaptureForm entryId={draft.id} phase={phase} store={store} /> : null}
      </section>
      <EntryHistoryList entries={draft.entries} kind={phase ? "phase_review" : "daily_review"} />
    </div>
  );
}

function EntryHistoryList({ entries, kind }: { entries: StructuredEntry[]; kind: StructuredEntryKind }) {
  const title = kind === "diary" ? "往日日记" : kind === "insight" ? "往日心得" : "历史复盘";
  const prior = entries.slice(1).slice(0, 12);
  return (
    <aside className="content-card side-tip">
      <h3>{title}</h3>
      {prior.length > 0 ? (
        <ul className="entry-history-list" role="list">
          {prior.map((entry) => (
            <li key={entry.id}>
              <time>{entry.entry_date}</time>
              <span>{entry.title || (kind === "diary" ? "无题日记" : kind === "insight" ? "无题心得" : "未命名")}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p>还没有更早的记录。</p>
      )}
    </aside>
  );
}

function MemoryCaptureForm({ entryId, phase, store }: { entryId: string; phase: boolean; store: ReturnType<typeof useStore> }) {
  const [open, setOpen] = useState(false);
  const [claim, setClaim] = useState("");
  const [scopeKind, setScopeKind] = useState<"global" | "scenario" | "project">("global");
  const [scenario, setScenario] = useState(phase ? "learning" : "information_execution");
  const [projectId, setProjectId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const submit = async () => {
    if (!claim.trim()) { setMessage("请先写下你希望 LifeOS 记住的一条认知。"); return; }
    if (scopeKind === "project" && !projectId.trim()) { setMessage("项目范围必须填写项目 ID，避免项目记忆串用。"); return; }
    const scope: MemoryScope = scopeKind === "global" ? { kind: "global" } : scopeKind === "scenario" ? { kind: "scenario", scenario_type: scenario } : { kind: "project", project_id: projectId.trim(), scenario_type: "project" };
    setBusy(true); setMessage("");
    try {
      const result = await proposeEntryMemoryCandidate(entryId, { claim, scope, category: scopeKind === "project" ? "project" : "user" });
      await store.refreshAll();
      setMessage(result.status === "candidate" ? "已提交为待审核候选。请到「系统后台 → Memory → Candidates」确认采纳或拒绝。" : "这条来源修订已处理过，未重复创建候选。");
      setClaim("");
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };
  return <div style={{ marginTop: 14, padding: 12, border: "1px solid var(--bd-1)", borderRadius: "var(--r-2)" }}>
    <button type="button" className="ghost" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "收起记忆提炼" : "从这条记录提炼一条记忆候选"}</button>
    {open ? <div className="col" style={{ gap: 8, marginTop: 10 }}>
      <p className="mono muted" style={{ margin: 0, fontSize: 10 }}>手动写出长期有用的结论；原始规划/复盘仍留在 SQLite，候选必须经你审核后才会成为 Memory。</p>
      <label className="col" style={{ gap: 4, fontSize: 12 }}>希望 LifeOS 记住什么？<textarea value={claim} onChange={(e) => setClaim(e.target.value)} rows={3} placeholder="例如：连续安排过多晚间任务会降低第二天的专注度。" /></label>
      <label className="row" style={{ gap: 8, flexWrap: "wrap", fontSize: 12 }}>记忆范围<select value={scopeKind} onChange={(e) => setScopeKind(e.target.value as typeof scopeKind)}><option value="global">全局核心</option><option value="scenario">场景</option><option value="project">具体项目</option></select></label>
      {scopeKind === "scenario" ? <label className="row" style={{ gap: 8, fontSize: 12 }}>场景<select value={scenario} onChange={(e) => setScenario(e.target.value)}><option value="learning">学习型</option><option value="project">项目型</option><option value="document">文档型</option><option value="information_execution">信息型执行</option><option value="external_operation">外部操作型</option></select></label> : null}
      {scopeKind === "project" ? <label className="col" style={{ gap: 4, fontSize: 12 }}>项目 ID<input value={projectId} onChange={(e) => setProjectId(e.target.value)} placeholder="填写稳定的项目标识" /></label> : null}
      <button className="green-button" onClick={() => void submit()} disabled={busy || store.state.ui.dataMode !== "backend"}>{busy ? "提交中…" : "提交候选，等待我审核"}</button>
      {store.state.ui.dataMode !== "backend" ? <span className="mono muted" style={{ fontSize: 10 }}>预览模式不能写入记忆候选。</span> : null}
      {message ? <div role="status" className="mono muted" style={{ fontSize: 10 }}>{message}</div> : null}
    </div> : null}
  </div>;
}

function FeedbackPage() {
  const draft = useEntryDraft("feedback", {});
  const [category, setCategory] = useState("使用感受");
  return (
    <div className="feedback-layout">
      <section className="content-card feedback-main">
        <h2 className="editor-card-title">哪里让你觉得顺手？哪里还不够像你？</h2>
        <RichEditor
          value={draft.content}
          onChange={draft.setContent}
          placeholder="可以是一句话，也可以是一段具体的经历…"
          minHeight={160}
          ariaLabel="反馈正文"
        />
        <div className="feedback-tags">
          {["功能建议", "使用感受", "发现问题", "其他"].map((tag) => (
            <button className={category === tag ? "selected" : ""} key={tag} onClick={() => setCategory(tag)}>{tag}</button>
          ))}
        </div>
        <div className="editor-footer">
          <span>内容会保存到本地 SQLite</span>
          <button className="green-button" onClick={() => void draft.save({ metadata: { category } })} disabled={draft.saving}>
            {draft.saving ? "提交中…" : "提交反馈"}
            <IconArrowRight size={14} />
          </button>
        </div>
      </section>
      <section className="content-card feedback-history">
        <div className="block-head">
          <h2 className="editor-card-title">你的声音</h2>
          <span className="block-meta">来自 SQLite</span>
        </div>
        {draft.content
          ? <div className="feedback-note"><IconCheck size={12} /><div><strong>{draft.content.replace(/<[^>]+>/g, " ").slice(0, 24).trim()}{draft.content.length > 24 ? "…" : ""}</strong><small>刚刚 · 已保存</small></div></div>
          : <div className="state-empty">还没有新的反馈</div>}
      </section>
    </div>
  );
}

function DiaryPage() {
  const draft = useEntryDraft("diary", {});
  const moods: { id: string; label: string; icon: React.ReactNode }[] = [
    { id: "calm", label: "平静", icon: <IconCircleDot size={14} /> },
    { id: "tired", label: "有点累", icon: <IconCircleDot size={14} /> },
    { id: "energized", label: "充满能量", icon: <IconCircleDot size={14} /> },
    { id: "unsure", label: "说不清", icon: <IconCircleDot size={14} /> },
  ];
  return (
    <div className="diary-layout">
      <section className="content-card diary-editor">
        <div className="block-head">
          <h2 className="editor-card-title">今天的日记</h2>
          <span className="block-meta">{draft.id ? "已保存" : "新记录"}</span>
        </div>
        <RichEditor
          value={draft.content}
          onChange={draft.setContent}
          placeholder="今天有什么值得被写下来？"
          minHeight={280}
          ariaLabel="今日日记"
        />
        <div className="diary-mood">
          <span>今天的心情</span>
          {moods.map((mood) => (
            <button className={draft.mood === mood.id ? "selected" : ""} key={mood.id} onClick={() => draft.setMood(mood.id)}>
              {mood.icon}
              <span>{mood.label}</span>
            </button>
          ))}
        </div>
        <div className="editor-footer">
          <span>内容会保存到本地 SQLite</span>
          <button className="green-button" onClick={() => void draft.save()} disabled={draft.saving}>
            {draft.saving ? "保存中…" : "保存日记"}
            <IconArrowRight size={14} />
          </button>
        </div>
      </section>
      <EntryHistoryList entries={draft.entries} kind="diary" />
    </div>
  );
}

function InsightPage() {
  const draft = useEntryDraft("insight", {});
  return (
    <div className="insight-layout">
      <section className="content-card insight-editor">
        <div className="block-head">
          <h2 className="editor-card-title">记录一个正在发酵的想法</h2>
          <span className="block-meta">{draft.id ? "已保存" : "新记录"}</span>
        </div>
        <input className="insight-title" placeholder="先写一个标题…" value={draft.title} onChange={(event) => draft.setTitle(event.target.value)} />
        <RichEditor
          value={draft.content}
          onChange={draft.setContent}
          placeholder="一段阅读后的感受、一次旅途中的发现，或者一个你不想忘记的瞬间…"
          minHeight={280}
          ariaLabel="心得正文"
        />
        <div className="editor-footer">
          <span>内容会保存到本地 SQLite</span>
          <button className="green-button" onClick={() => void draft.save()} disabled={draft.saving}>
            {draft.saving ? "保存中…" : "保存心得"}
            <IconArrowRight size={14} />
          </button>
        </div>
      </section>
      <EntryHistoryList entries={draft.entries} kind="insight" />
    </div>
  );
}

function AdminPage({ store }: { store: ReturnType<typeof useStore> }) { return <div className="admin-page"><div className="admin-banner"><div><span className="card-kicker">系统后台</span><h2>工程信息集中在这里</h2><p>普通使用页面保持安静。只有进入后台，才会看到 Agent、事件、记忆和 Trace 等运行细节。</p></div><span className="admin-badge">开发者视图</span></div><div className="admin-flow"><DataFlowView store={store} /></div><div className="admin-grid"><RuntimeRail store={store} /><EventsPanel store={store} /><MemoryPanel store={store} /><SkillsPanel store={store} /><PermissionsPanel store={store} /><TracePanel store={store} /></div></div>; }

function MemoryPage({ store }: { store: ReturnType<typeof useStore> }) {
  return (
    <div className="memory-page">
      <MemoryPanel store={store} />
    </div>
  );
}

function Task({ label, done = false }: { label: string; done?: boolean }) {
  return (
    <div className={`task-row ${done ? "task-done" : ""}`}>
      <span className="task-check">{done ? <IconCheck size={12} /> : null}</span>
      <span>{label}</span>
      {done ? <small>完成</small> : null}
    </div>
  );
}
