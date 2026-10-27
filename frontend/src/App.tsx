import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "./state/store";
import { useAgentStore } from "./state/agentStore";
import { useAgentStream } from "./hooks/useAgentStream";
import { listEntries, proposeEntryMemoryCandidate, saveEntry } from "./api/client";
import type { MemoryScope, StructuredEntry, StructuredEntryKind } from "./api/types";
import { ChatPanel } from "./panels/ChatPanel";
import { AgentPanel } from "./panels/AgentPanel";
import { AgentsSection } from "./panels/AgentsSection";
import { AgentPeekBar } from "./panels/AgentPeekBar";
import { RuntimeRail } from "./panels/RuntimeRail";
import { EventsPanel } from "./panels/EventsPanel";
import { MemoryPanel } from "./panels/MemoryPanel";
import { TracePanel } from "./panels/TracePanel";
import { SkillsPanel } from "./panels/SkillsPanel";
import { PermissionsPanel } from "./panels/PermissionsPanel";
import { DataFlowView } from "./panels/DataFlowView";
import { SettingsPage } from "./panels/SettingsPage";
import { WorkCalendar } from "./components/WorkCalendar";
import { RichEditor } from "./components/RichEditor";
import { AvatarButton } from "./components/AvatarButton";
import {
  IconArrowRight,
  IconBook,
  IconBolt,
  IconCalendar,
  IconCheck,
  IconChevron,
  IconCircleDot,
  IconHome,
  IconInbox,
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

const sectionMeta = {
  calendar: { crumb: "记录", title: "工作历", description: "汇总 LifeOS 已保存的每日与阶段记录。" },
  home: { crumb: "工作台", title: "今日概览", description: "把计划变成行动，把行动留下痕迹。" },
  "daily-plan": { crumb: "计划", title: "每日规划", description: "不追求塞满日程，只选择真正值得推进的三件事。" },
  "daily-review": { crumb: "复盘", title: "每日复盘", description: "记录发生过什么，也看见自己做得好的地方。" },
  "phase-plan": { crumb: "计划", title: "阶段性规划", description: "阶段性目标不必宏大，但需要可以被看见、被推进。" },
  "phase-review": { crumb: "复盘", title: "阶段性复盘", description: "回看过去一段时间，判断什么值得继续，什么应该放下。" },
  chat: { crumb: "工作台", title: "对话", description: "LifeOS 会记住重要的上下文，陪你把想法变成下一步。" },
  agents: { crumb: "工作台", title: "本地 Agent", description: "LifeOS 负责规划与拆解，本机 Agent 负责动手。审批始终由你点。" },
  feedback: { crumb: "反馈", title: "反馈", description: "告诉我们哪里顺手，哪里还可以更贴近你的工作方式。" },
  diary: { crumb: "记录", title: "日记", description: "不必写得完整，想到什么就从哪里开始。" },
  insight: { crumb: "记录", title: "心得 / 体验", description: "记录一个念头、一种感受，或者一次值得记住的体验。" },
  memory: { crumb: "开发", title: "记忆候选", description: "候选、生命周期、纠正 / 撤回、画像重建、Markdown 镜像。" },
} as Record<SectionId, { crumb: string; title: string; description: string }>;

function NavIconGlyph({ name }: { name: NavIcon }) {
  if (name === "home") return <IconHome size={17} />;
  if (name === "message") return <IconMessage size={17} />;
  if (name === "calendar") return <IconCalendar size={17} />;
  if (name === "book") return <IconBook size={17} />;
  if (name === "bolt") return <IconBolt size={17} />;
  return <IconSpark size={17} />;
}

sectionMeta.settings = { crumb: "系统", title: "设置", description: "管理模型 Provider、API 连接和工作区外观。" };

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
  const [settingsOpen, setSettingsOpen] = useState(false);
  const meta = sectionMeta[active];

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
    setSettingsOpen(false);
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
          <div className="breadcrumb"><span>LifeOS</span><i>/</i><strong>{meta.crumb}</strong></div>
          <div className="header-actions">
            <span className="sync-label"><span className="status-orb" />刚刚同步</span>
            <button className="header-icon-button" onClick={() => setDark(!dark)} title="切换主题" aria-label={`切换到${dark ? "浅色" : "夜间"}主题`} aria-pressed={dark}>{dark ? <IconSun size={16} /> : <IconSpark size={16} />}</button>
            <button className="header-icon-button" onClick={() => { setSettingsOpen(false); select("settings"); }} title="设置" aria-label="设置" aria-expanded={active === "settings"}><IconSettings size={16} /></button>
            <AvatarButton />
          </div>
          {settingsOpen ? (
            <div className="settings-popover">
              <strong>工作区设置</strong>
              <span>主题：{dark ? "夜间" : "浅色薄荷"}</span>
              <span>数据模式：{store.state.ui.dataMode === "backend" ? "实时后端" : "本地预览"}</span>
            </div>
          ) : null}
        </header>

        <main id="main-content" className="workspace-main">
          {/* agents 页自带标题块（参考界面），隐藏外层 page-intro，避免双标题。 */}
          <div className={`page-intro ${active === "chat" || active === "agents" ? "page-intro-chat" : ""}`}>
            <h1>{meta.title}</h1>
            <p>{meta.description}</p>
          </div>
          <SectionContent active={active} store={store} agent={agent} api={api} onNavigate={select} dark={dark} onDarkChange={setDark} />
        </main>
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
}: {
  active: SectionId;
  store: ReturnType<typeof useStore>;
  agent: ReturnType<typeof useAgentStore>;
  api: ReturnType<typeof useAgentStream>;
  onNavigate: (id: SectionId) => void;
  dark: boolean;
  onDarkChange: (dark: boolean) => void;
}) {
  if (active === "chat") {
    // 对话整页：直接占满主区，不再套 content-card（Impeccable 黑名单：卡片当容器）。
    // Agent 侧栏按需展开，只有用户主动打开时才出现，不参与默认布局。
    const zuo = (
      <div className="chat-host">
        <ChatPanel store={store} agent={agent} api={api} />
      </div>
    );
    if (agent.state.layout !== "split") return zuo;
    return (
      <div className="chat-split-grid">
        {zuo}
        <AgentPanel store={agent} api={api}
          onCandidateCreated={() => void store.refreshAll()}
          onCollapse={() => agent.setLayout("collapsed")} />
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

function HomePage({ store, onNavigate }: { store: ReturnType<typeof useStore>; onNavigate: (id: SectionId) => void }) {
  const completed = 2;
  const total = 4;
  const progress = useMemo(() => `${Math.round((completed / total) * 100)}%`, []);
  const today = new Intl.DateTimeFormat("zh-CN", { weekday: "short", month: "long", day: "numeric" }).format(new Date());
  return <div className="home-grid">
    <section className="focus-card content-card">
      <div className="focus-top"><span className="card-kicker">今日焦点</span><span className="focus-date">{today}</span></div>
      <h2>慢一点，但要向前。</h2>
      <p>今天适合完成一件需要专注的事，也适合给自己留一点空白。</p>
      <button className="green-button" onClick={() => onNavigate("daily-plan")}>开始今日规划 <span>→</span></button>
      <div className="leaf-decoration" aria-hidden="true">✳</div>
    </section>
    <section className="content-card progress-card"><div className="card-heading"><div><span className="card-kicker">今日进度</span><h2>{progress}</h2></div><span className="progress-ring">{completed}/{total}</span></div><div className="progress-track"><span style={{ width: progress }} /></div><p>已完成 {completed} 项，还有 2 项等待你的注意。</p><button className="text-button" onClick={() => onNavigate("daily-plan")}>查看今日清单 →</button></section>
    <section className="content-card today-card"><div className="card-heading"><div><span className="card-kicker">接下来</span><h2>今日安排</h2></div><span className="soft-count">4 件</span></div><Task label="写下本周的阶段目标" done /><Task label="完成课程阅读 · 45 分钟" done /><Task label="整理项目反馈" /><Task label="晚间复盘" /></section>
    <section className="content-card rhythm-card"><div className="card-heading"><div><span className="card-kicker">生活节奏</span><h2>给自己留一点余地</h2></div><span className="soft-count">本周 · 4 / 7 天</span></div><p className="pulse-copy">持续前进不一定要很用力。今天完成重要的事，也记得给自己一点休息。</p><div className="week-dots"><span className="filled" /><span className="filled" /><span className="filled" /><span className="filled" /><span /><span /><span /></div><div className="rhythm-footer"><span>本周已经记录了 4 个值得记住的瞬间</span><button className="text-button" onClick={() => onNavigate("diary")}>写一篇日记 →</button></div></section>
    <section className="content-card quote-card"><span className="quote-mark">“</span><p>真正重要的不是把每件事都做好，而是知道此刻什么值得被做好。</p><span className="quote-source">— 今日提醒</span></section>
    <section className="content-card recent-card"><div className="card-heading"><div><span className="card-kicker">最近记录</span><h2>工作台动态</h2></div><button className="text-button" onClick={() => onNavigate("feedback")}>查看全部</button></div><div className="recent-row"><span className="recent-icon">↗</span><div><strong>完成了一次对话</strong><small>刚刚 · 已写入事件队列</small></div><span className="recent-status">已记录</span></div><div className="recent-row"><span className="recent-icon">✦</span><div><strong>收到一个新的反馈</strong><small>昨天 · 关于复盘流程</small></div><span className="recent-status">待处理</span></div></section>
  </div>;
}

/**
 * 结构化记录草稿：一类 kind 下可以有**多条**（每天一条规划、一篇日记…），
 * 所以这里不再是"打开第一条"，而是"持有一份列表 + 当前选中项"。
 *
 * - 加载时按 entry_date 分组，日期倒序（最新在前）
 * - 选中项优先落在今天；今天没有就落到最新一条
 * - save() 有 id 就 PUT 更新，没 id 就 POST 新建（"同一天再存一次"是覆盖，
 *   "换一天再存"是新增）
 */
function useEntryDraft(kind: StructuredEntryKind, initial: { title?: string; content?: string }) {
  const [entries, setEntries] = useState<StructuredEntry[]>([]);
  const [activeId, setActiveId] = useState<string | undefined>(undefined);
  const [title, setTitle] = useState(initial.title ?? "");
  const [content, setContent] = useState(initial.content ?? "");
  const [mood, setMood] = useState<string | null>(null);
  const [metadata, setMetadata] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const todayKey = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const seedTitle = initial.title ?? "";
  const seedContent = initial.content ?? "";

  /** 载入一条记录；传 undefined 就开空白草稿（id 空 → save 时 POST 新建）。 */
  const applyEntry = useCallback((entry: StructuredEntry | undefined) => {
    if (!entry) {
      setActiveId(undefined);
      setTitle(seedTitle);
      setContent(seedContent);
      setMood(null);
      setMetadata({});
      setSavedAt(null);
      return;
    }
    setActiveId(entry.id);
    setTitle(entry.title);
    setContent(entry.content);
    setMood(entry.mood ?? null);
    setMetadata(entry.metadata ?? {});
    setSavedAt(new Date(entry.updated_at).getTime());
  }, [seedTitle, seedContent]);

  /** 按日期分组 + 倒序，给日期 chips 用。 */
  const days = useMemo(() => {
    const groups = new Map<string, StructuredEntry[]>();
    for (const entry of entries) {
      const key = entry.entry_date.slice(0, 10);
      const bucket = groups.get(key) ?? [];
      bucket.push(entry);
      groups.set(key, bucket);
    }
    return [...groups.entries()]
      .sort((a, b) => b[0].localeCompare(a[0]))
      .map(([date, items]) => ({ date, entries: items }));
  }, [entries]);

  const activeDate = useMemo(
    () => entries.find((it) => it.id === activeId)?.entry_date.slice(0, 10) ?? todayKey,
    [entries, activeId, todayKey],
  );

  useEffect(() => {
    let alive = true;
    setError(null);
    listEntries(kind)
      .then((items) => {
        if (!alive) return;
        setEntries(items);
        const todayEntry = items.find((it) => it.entry_date.slice(0, 10) === todayKey);
        applyEntry(todayEntry ?? items[0]);
        setLoaded(true);
      })
      .catch((e) => {
        if (!alive) return;
        setError(e instanceof Error ? e.message : String(e));
        setLoaded(true);
      });
    return () => { alive = false; };
  }, [kind, todayKey, applyEntry]);

  /** 切到某一天。有记录就载入，没有就开空白草稿。 */
  const selectDate = useCallback((date: string) => {
    setError(null);
    applyEntry(entries.find((it) => it.entry_date.slice(0, 10) === date));
  }, [entries, applyEntry]);

  /** 开一条全新的空白记录。 */
  const startBlank = useCallback(() => {
    setError(null);
    applyEntry(undefined);
  }, [applyEntry]);

  const save = async (
    overrides: Partial<{
      title: string; content: string; mood: string | null;
      metadata: Record<string, unknown>; entry_date: string;
    }> = {},
  ) => {
    setSaving(true);
    setError(null);
    try {
      const entry = await saveEntry({
        id: activeId,
        kind,
        entry_date: overrides.entry_date ?? activeDate,
        title: overrides.title ?? title,
        content: overrides.content ?? content,
        mood: overrides.mood ?? mood,
        metadata: overrides.metadata ?? metadata,
      });
      setActiveId(entry.id);
      setTitle(entry.title);
      setContent(entry.content);
      setMood(entry.mood ?? null);
      setMetadata(entry.metadata ?? {});
      setSavedAt(Date.now());
      setEntries(await listEntries(kind));
      return entry;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      throw e;
    } finally {
      setSaving(false);
    }
  };

  return {
    id: activeId, activeDate,
    title, setTitle,
    content, setContent,
    mood, setMood,
    metadata, setMetadata,
    saving, savedAt, error, loaded,
    save,
    entries, days, selectDate, startBlank,
  };
}

/** 日期 chips：横向滚动的"每天一条"选择器 + 新建按钮。 */
function DateChips({
  days,
  activeDate,
  todayKey,
  onSelect,
  onNew,
  emptyHint,
}: {
  days: { date: string; entries: StructuredEntry[] }[];
  activeDate: string;
  todayKey: string;
  onSelect: (date: string) => void;
  onNew: () => void;
  emptyHint: string;
}) {
  const withToday = days.some((d) => d.date === todayKey)
    ? days
    : [{ date: todayKey, entries: [] }, ...days];
  return (
    <div className="date-chips" role="tablist" aria-label="按日期切换记录">
      <div className="date-chips-scroll">
        {withToday.map((day) => {
          const active = day.date === activeDate;
          const isToday = day.date === todayKey;
          const count = day.entries.length;
          return (
            <button
              key={day.date}
              role="tab"
              aria-selected={active}
              className={`date-chip ${active ? "is-active" : ""} ${isToday ? "is-today" : ""}`}
              onClick={() => onSelect(day.date)}
              title={`${day.date}${count ? ` · ${count} 条` : " · 还没有记录"}`}
            >
              <span className="date-chip-main">{day.date.slice(5).replace("-", "/")}</span>
              <span className="date-chip-sub">
                {isToday ? "今天" : count ? `${count} 条` : "空"}
              </span>
            </button>
          );
        })}
      </div>
      <button className="date-chips-new" onClick={onNew} title={emptyHint}>
        <IconPlus size={13} />
        新建
      </button>
    </div>
  );
}

/** 保存反馈条：保存位置 + 时间 + 错误。 */
function SaveStatus({
  savedAt,
  error,
  saving,
  kindLabel,
  entryDate,
}: {
  savedAt: number | null;
  error: string | null;
  saving: boolean;
  kindLabel: string;
  entryDate: string;
}) {
  if (error) {
    return (
      <div className="save-status is-error" role="alert">
        <span className="save-status-dot" />
        保存失败：{error}
      </div>
    );
  }
  if (saving) {
    return (
      <div className="save-status is-saving" role="status">
        <span className="save-status-dot" />
        正在写入本地 SQLite…
      </div>
    );
  }
  if (savedAt) {
    const time = new Date(savedAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    return (
      <div className="save-status is-saved" role="status">
        <IconCheck size={12} />
        已保存到本地 SQLite · {kindLabel} · {entryDate} · {time}
      </div>
    );
  }
  return (
    <div className="save-status is-idle">
      <span className="save-status-dot" />
      尚未保存 · 内容在 {kindLabel} · {entryDate}
    </div>
  );
}

function PlanningPage({ phase, store }: { phase: boolean; store: ReturnType<typeof useStore> }) {
  const draft = useEntryDraft(phase ? "phase_plan" : "daily_plan", { content: phase ? "建立一个更稳定的学习与创作节奏。" : "" });
  const todayKey = new Date().toISOString().slice(0, 10);
  return (
    <div className="planning-layout">
      <section className="content-card editor-card">
        <div className="block-head">
          <h2 className="editor-card-title">{phase ? "未来 90 天，我想靠近什么？" : "今天最值得推进的三件事"}</h2>
          <span className="block-meta">{draft.loaded ? (draft.id ? `已保存 ${draft.entries.length} 条` : "新记录") : "读取中"}</span>
        </div>
        <DateChips
          days={draft.days}
          activeDate={draft.activeDate}
          todayKey={todayKey}
          onSelect={draft.selectDate}
          onNew={draft.startBlank}
          emptyHint={phase ? "新建一条阶段规划" : "新建一条今日规划"}
        />
        <RichEditor
          value={draft.content}
          onChange={draft.setContent}
          placeholder={phase ? "写下这个阶段最想完成、体验或改变的事情…" : "从最重要的事情开始，不必一次写完…"}
          ariaLabel={phase ? "阶段性规划" : "今日规划"}
        />
        <div className="editor-footer">
          <SaveStatus savedAt={draft.savedAt} error={draft.error} saving={draft.saving} kindLabel={phase ? "阶段规划" : "每日规划"} entryDate={draft.activeDate} />
          <button className="green-button" onClick={() => void draft.save().catch(() => undefined)} disabled={draft.saving}>
            {draft.saving ? "保存中…" : draft.savedAt ? "再次保存" : "保存规划"}
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
  const todayKey = new Date().toISOString().slice(0, 10);

  // 每日复盘时拉取"今日规划"作为勾选清单来源；阶段性复盘不做这个。
  useEffect(() => {
    if (phase) return;
    let alive = true;
    listEntries("daily_plan").then((items) => {
      if (!alive) return;
      const todayEntry = items.find((it) => it.entry_date.slice(0, 10) === todayKey) ?? items[0];
      if (!todayEntry) { setChecks([]); return; }
      const lines = todayEntry.content
        .replace(/<[^>]+>/g, "\n")
        .split(/\r?\n/)
        .map((line) => line.replace(/^[-*•·\s]+/, "").trim())
        .filter((line) => line.length > 0 && line.length < 200);
      const saved = (Array.isArray(draft.metadata.checks) ? draft.metadata.checks : []) as { id: string; label: string; done: boolean }[];
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
  }, [phase, draft.id, todayKey]);

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
    void draft.save({ content: draft.content, metadata: { checks } }).catch(() => undefined);

  return (
    <div className="review-layout">
      <section className="content-card review-prompts">
        <div className="block-head">
          <h2 className="editor-card-title">{phase ? "回看这段路，你发现了什么？" : "今天发生了什么？"}</h2>
          <span className="block-meta">{draft.loaded ? (draft.id ? `已保存 ${draft.entries.length} 条` : "新记录") : "读取中"}</span>
        </div>

        <DateChips
          days={draft.days}
          activeDate={draft.activeDate}
          todayKey={todayKey}
          onSelect={draft.selectDate}
          onNew={draft.startBlank}
          emptyHint={phase ? "新建一条阶段复盘" : "新建一条每日复盘"}
        />

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
          <SaveStatus savedAt={draft.savedAt} error={draft.error} saving={draft.saving} kindLabel={phase ? "阶段复盘" : "每日复盘"} entryDate={draft.activeDate} />
          <button className="green-button" onClick={save} disabled={draft.saving}>
            {draft.saving ? "保存中…" : draft.savedAt ? "再次保存" : "完成复盘"}
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
              <time>{entry.entry_date.slice(0, 10)}</time>
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
  const todayKey = new Date().toISOString().slice(0, 10);
  return (
    <div className="feedback-layout">
      <section className="content-card feedback-main">
        <h2 className="editor-card-title">哪里让你觉得顺手？哪里还不够像你？</h2>
        <DateChips
          days={draft.days}
          activeDate={draft.activeDate}
          todayKey={todayKey}
          onSelect={draft.selectDate}
          onNew={draft.startBlank}
          emptyHint="新建一条反馈"
        />
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
          <SaveStatus savedAt={draft.savedAt} error={draft.error} saving={draft.saving} kindLabel="反馈" entryDate={draft.activeDate} />
          <button className="green-button" onClick={() => void draft.save({ metadata: { category } }).catch(() => undefined)} disabled={draft.saving}>
            {draft.saving ? "提交中…" : draft.savedAt ? "再次提交" : "提交反馈"}
            <IconArrowRight size={14} />
          </button>
        </div>
      </section>
      <section className="content-card feedback-history">
        <div className="block-head">
          <h2 className="editor-card-title">你的声音</h2>
          <span className="block-meta">来自 SQLite</span>
        </div>
        {draft.entries.length > 0 ? (
          <ul className="feedback-note-list" role="list">
            {draft.entries.slice(0, 8).map((entry) => (
              <li key={entry.id} className="feedback-note">
                <IconCheck size={12} />
                <div>
                  <strong>{entry.content.replace(/<[^>]+>/g, " ").slice(0, 24).trim()}{entry.content.length > 24 ? "…" : ""}</strong>
                  <small>{entry.entry_date.slice(0, 10)} · 已保存</small>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div className="state-empty">还没有新的反馈</div>
        )}
      </section>
    </div>
  );
}

function DiaryPage() {
  const draft = useEntryDraft("diary", {});
  const todayKey = new Date().toISOString().slice(0, 10);
  const moods: { id: string; label: string }[] = [
    { id: "calm", label: "平静" },
    { id: "tired", label: "有点累" },
    { id: "energized", label: "充满能量" },
    { id: "unsure", label: "说不清" },
  ];
  return (
    <div className="diary-layout">
      <section className="content-card diary-editor">
        <div className="block-head">
          <h2 className="editor-card-title">今天的日记</h2>
          <span className="block-meta">{draft.loaded ? (draft.id ? `已保存 ${draft.entries.length} 篇` : "新记录") : "读取中"}</span>
        </div>
        <DateChips
          days={draft.days}
          activeDate={draft.activeDate}
          todayKey={todayKey}
          onSelect={draft.selectDate}
          onNew={draft.startBlank}
          emptyHint="新建一篇日记"
        />
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
              <IconCircleDot size={13} />
              <span>{mood.label}</span>
            </button>
          ))}
        </div>
        <div className="editor-footer">
          <SaveStatus savedAt={draft.savedAt} error={draft.error} saving={draft.saving} kindLabel="日记" entryDate={draft.activeDate} />
          <button className="green-button" onClick={() => void draft.save().catch(() => undefined)} disabled={draft.saving}>
            {draft.saving ? "保存中…" : draft.savedAt ? "再次保存" : "保存日记"}
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
  const todayKey = new Date().toISOString().slice(0, 10);
  return (
    <div className="insight-layout">
      <section className="content-card insight-editor">
        <div className="block-head">
          <h2 className="editor-card-title">记录一个正在发酵的想法</h2>
          <span className="block-meta">{draft.loaded ? (draft.id ? `已保存 ${draft.entries.length} 篇` : "新记录") : "读取中"}</span>
        </div>
        <DateChips
          days={draft.days}
          activeDate={draft.activeDate}
          todayKey={todayKey}
          onSelect={draft.selectDate}
          onNew={draft.startBlank}
          emptyHint="新建一条心得"
        />
        <input className="insight-title" placeholder="先写一个标题…" value={draft.title} onChange={(event) => draft.setTitle(event.target.value)} />
        <RichEditor
          value={draft.content}
          onChange={draft.setContent}
          placeholder="一段阅读后的感受、一次旅途中的发现，或者一个你不想忘记的瞬间…"
          minHeight={280}
          ariaLabel="心得正文"
        />
        <div className="editor-footer">
          <SaveStatus savedAt={draft.savedAt} error={draft.error} saving={draft.saving} kindLabel="心得" entryDate={draft.activeDate} />
          <button className="green-button" onClick={() => void draft.save().catch(() => undefined)} disabled={draft.saving}>
            {draft.saving ? "保存中…" : draft.savedAt ? "再次保存" : "保存心得"}
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

function Task({ label, done = false }: { label: string; done?: boolean }) { return <div className={`task-row ${done ? "task-done" : ""}`}><span className="task-check">{done ? "✓" : ""}</span><span>{label}</span>{done ? <small>完成</small> : null}</div>; }
