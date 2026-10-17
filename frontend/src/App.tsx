import { useEffect, useRef, useState } from "react";
import { useStore } from "./state/store";
import { useAgentStore } from "./state/agentStore";
import { useAgentStream } from "./hooks/useAgentStream";
import { listEntries, proposeEntryMemoryCandidate, saveEntry } from "./api/client";
import type { MemoryScope, StructuredEntry, StructuredEntryKind } from "./api/types";
import { ChatPanel } from "./panels/ChatPanel";
import { AgentPanel } from "./panels/AgentPanel";
import { AgentsSection } from "./panels/AgentsSection";
import { AgentPeekBar } from "./panels/AgentPeekBar";
import { SettingsPage } from "./panels/SettingsPage";
import { WorkCalendar } from "./components/WorkCalendar";
import { TodayOverviewCards } from "./components/TodayOverviewCards";
import { DailyReminderCard } from "./components/DailyReminderCard";
import { EntryHistory } from "./components/EntryHistory";
import { InboxButton } from "./components/InboxButton";
import { MarkdownEditor } from "./components/MarkdownEditor";
import { ResizableChatSplit } from "./components/ResizableChatSplit";
import { extractPlanItems, localDateKey } from "./utils/planItems";
import { AccountMenu, AuthGate } from "./components/AuthGate";
import { IconBook, IconBolt, IconCalendar, IconHome, IconMessage, IconSettings, IconSpark, IconSun } from "./components/Icons";

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
  calendar: { eyebrow: "记录 · 工作历", title: "回看你的日常轨迹", description: "汇总 LifeOS 已保存的每日与阶段记录。" },
  home: { eyebrow: "工作台 · 今日概览", title: "今天，先照顾最重要的事", description: "把计划变成行动，把行动留下痕迹。" },
  "daily-plan": { eyebrow: "计划 · 每日", title: "给今天一个清晰的起点", description: "不追求塞满日程，只选择真正值得推进的三件事。" },
  "daily-review": { eyebrow: "复盘 · 每日", title: "把今天温柔地收好", description: "记录发生过什么，也看见自己做得好的地方。" },
  "phase-plan": { eyebrow: "计划 · 阶段", title: "把远方拆成下一步", description: "阶段性目标不必宏大，但需要可以被看见、被推进。" },
  "phase-review": { eyebrow: "复盘 · 阶段", title: "重新校准你的方向", description: "回看过去一段时间，判断什么值得继续，什么应该放下。" },
  chat: { eyebrow: "连接 · 对话", title: "和你的第二大脑聊聊", description: "LifeOS 会记住重要的上下文，陪你把想法变成下一步。" },
  agents: { eyebrow: "连接 · 本地 Agent", title: "把执行交给你机器上的 Agent", description: "LifeOS 负责规划与拆解，本机 Agent 负责动手。审批始终由你点。" },
  feedback: { eyebrow: "系统 · 反馈", title: "让 LifeOS 越来越懂你", description: "告诉我们哪里顺手，哪里还可以更贴近你的工作方式。" },
  diary: { eyebrow: "记录 · 日记", title: "给今天留一页空白", description: "不必写得完整，想到什么就从哪里开始。" },
  insight: { eyebrow: "沉淀 · 心得 / 体验", title: "把经历变成自己的东西", description: "记录一个念头、一种感受，或者一次值得记住的体验。" },
} as Record<SectionId, { eyebrow: string; title: string; description: string }>;

function NavIconGlyph({ name }: { name: NavIcon }) {
  if (name === "home") return <IconHome size={17} />;
  if (name === "message") return <IconMessage size={17} />;
  if (name === "calendar") return <IconCalendar size={17} />;
  if (name === "book") return <IconBook size={17} />;
  if (name === "bolt") return <IconBolt size={17} />;
  return <IconSpark size={17} />;
}

sectionMeta.settings = { eyebrow: "系统 · 设置", title: "让 LifeOS 按你的方式工作", description: "管理模型 Provider、API 连接和工作区外观。" };

export default function App() {
  const store = useStore();
  const agent = useAgentStore();
  const api = useAgentStream(agent);
  const [active, setActive] = useState<SectionId>("home");
  const [dark, setDark] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const meta = sectionMeta[active];
  const dateParts = new Intl.DateTimeFormat("zh-CN", { day: "numeric", month: "long" }).formatToParts(new Date());
  const todayDay = dateParts.find((part) => part.type === "day")?.value ?? "";
  const todayMonth = dateParts.find((part) => part.type === "month")?.value ?? "";

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
  };

  // 登录闸（方案 6.4）：未登录渲染登录页/首启向导，任何 401 都会被切回来。
  return (
    <AuthGate>
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
      </aside>

      <div className="content-shell">
        <header className="workspace-header">
          <div className="breadcrumb"><span>LifeOS</span><i>/</i><strong>{meta.eyebrow.split(" · ")[0]}</strong></div>
          <div className="header-actions">
            <span className="sync-label"><span className="status-orb" />刚刚同步</span>
            <InboxButton agent={agent} onOpenAgent={() => { agent.setLayout("split"); select("chat"); }} />
            <button className="header-icon-button" onClick={() => setDark(!dark)} title="切换主题" aria-label={`切换到${dark ? "浅色" : "夜间"}主题`} aria-pressed={dark}>{dark ? <IconSun size={16} /> : <IconSpark size={16} />}</button>
            <button className="header-icon-button" onClick={() => { setSettingsOpen(false); select("settings"); }} title="设置" aria-label="设置" aria-expanded={active === "settings"}><IconSettings size={16} /></button>
            <AccountMenu />
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
          <div className={`page-intro ${active === "chat" ? "page-intro-chat" : ""}`}>
            <div>
              <div className="page-eyebrow">{meta.eyebrow}</div>
              <h1>{meta.title}</h1>
              <p>{meta.description}</p>
            </div>
            <div className="intro-date"><span>今天</span><strong>{todayDay}</strong><small>{todayMonth}</small></div>
          </div>
          <SectionContent active={active} store={store} agent={agent} api={api} onNavigate={select} dark={dark} onDarkChange={setDark} />
        </main>
      </div>
    </div>
    </AuthGate>
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
    // 对话保持内容优先；Agent 执行面板按需展开。
    const zuo = (
      <div className="chat-page-grid">
        <section className="content-card chat-card">
          <ChatPanel store={store} agent={agent} api={api} />
        </section>
      </div>
    );
    return (
      <>
        <AgentPeekBar store={agent} api={api} onOpen={() => agent.setLayout("split")} />
        {agent.state.layout === "split" ? (
          <ResizableChatSplit
            chat={zuo}
            agent={<AgentPanel store={agent} api={api}
              onCandidateCreated={() => void store.refreshAll()}
              onCollapse={() => agent.setLayout("collapsed")} />}
          />
        ) : (
          zuo
        )}
      </>
    );
  }
  if (active === "agents") return <AgentsSection store={agent} api={api} onGoChat={() => onNavigate("chat")} />;
  if (active === "feedback") return <FeedbackPage />;
  if (active === "diary") return <DiaryPage />;
  if (active === "calendar") return <WorkCalendar onNavigate={onNavigate} />;
  if (active === "insight") return <InsightPage />;
  if (active === "settings") return <SettingsPage dark={dark} onDarkChange={onDarkChange} />;
  if (active === "daily-review" || active === "phase-review") return <ReviewPage phase={active === "phase-review"} store={store} />;
  if (active === "daily-plan" || active === "phase-plan") return <PlanningPage phase={active === "phase-plan"} store={store} />;
  return <HomePage onNavigate={onNavigate} />;
}

function HomePage({ onNavigate }: { onNavigate: (id: SectionId) => void }) {
  const today = new Intl.DateTimeFormat("zh-CN", { weekday: "short", month: "long", day: "numeric" }).format(new Date());
  return <div className="home-grid">
    <section className="focus-card content-card">
      <div className="focus-top"><span className="card-kicker">今日焦点</span><span className="focus-date">{today}</span></div>
      <h2>慢一点，但要向前。</h2>
      <p>今天适合完成一件需要专注的事，也适合给自己留一点空白。</p>
      <button className="green-button" onClick={() => onNavigate("daily-plan")}>开始今日规划 <span>→</span></button>
      <div className="leaf-decoration" aria-hidden="true">✳</div>
    </section>
    <TodayOverviewCards onViewPlan={() => onNavigate("daily-plan")} />
    <section className="content-card rhythm-card"><div className="card-heading"><div><span className="card-kicker">生活节奏</span><h2>给自己留一点余地</h2></div><span className="soft-count">本周 · 4 / 7 天</span></div><p className="pulse-copy">持续前进不一定要很用力。今天完成重要的事，也记得给自己一点休息。</p><div className="week-dots"><span className="filled" /><span className="filled" /><span className="filled" /><span className="filled" /><span /><span /><span /></div><div className="rhythm-footer"><span>本周已经记录了 4 个值得记住的瞬间</span><button className="text-button" onClick={() => onNavigate("diary")}>写一篇日记 →</button></div></section>
    <DailyReminderCard />
    <section className="content-card recent-card"><div className="card-heading"><div><span className="card-kicker">最近记录</span><h2>工作台动态</h2></div><button className="text-button" onClick={() => onNavigate("feedback")}>查看全部</button></div><div className="recent-row"><span className="recent-icon">↗</span><div><strong>完成了一次对话</strong><small>刚刚 · 已写入事件队列</small></div><span className="recent-status">已记录</span></div><div className="recent-row"><span className="recent-icon">✦</span><div><strong>收到一个新的反馈</strong><small>昨天 · 关于复盘流程</small></div><span className="recent-status">待处理</span></div></section>
  </div>;
}

function useEntryDraft(kind: StructuredEntryKind, initial: { title?: string; content?: string }) {
  const initialRef = useRef(initial);
  const [entries, setEntries] = useState<StructuredEntry[]>([]);
  const [id, setId] = useState<string>();
  const [entryDate, setEntryDate] = useState(localDateKey);
  const [title, setTitle] = useState(initial.title ?? "");
  const [content, setContent] = useState(initial.content ?? "");
  const [mood, setMood] = useState<string | null>(null);
  const [metadata, setMetadata] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    const reset = () => {
      setId(undefined);
      setEntryDate(localDateKey());
      setTitle(initialRef.current.title ?? "");
      setContent(initialRef.current.content ?? "");
      setMood(null);
      setMetadata({});
    };
    listEntries(kind).then((rows) => {
      if (!alive) return;
      setEntries(rows);
      const today = localDateKey();
      const daily = kind === "daily_plan" || kind === "daily_review" || kind === "diary";
      const entry = daily ? rows.find((row) => row.entry_date.slice(0, 10) === today) : rows[0];
      if (entry) {
        setId(entry.id);
        setEntryDate(entry.entry_date.slice(0, 10));
        setTitle(entry.title);
        setContent(entry.content);
        setMood(entry.mood ?? null);
        setMetadata(entry.metadata ?? {});
      } else {
        reset();
      }
      setLoaded(true);
    }).catch(() => {
      if (alive) {
        reset();
        setLoaded(true);
      }
    });
    return () => { alive = false; };
  }, [kind]);

  const openEntry = (entry: StructuredEntry) => {
    setId(entry.id);
    setEntryDate(entry.entry_date.slice(0, 10));
    setTitle(entry.title);
    setContent(entry.content);
    setMood(entry.mood ?? null);
    setMetadata(entry.metadata ?? {});
  };

  const startNew = () => {
    setId(undefined);
    setEntryDate(localDateKey());
    setTitle(initialRef.current.title ?? "");
    setContent(initialRef.current.content ?? "");
    setMood(null);
    setMetadata({});
  };

  const save = async (overrides: Partial<{ title: string; content: string; mood: string | null; metadata: Record<string, unknown> }> = {}) => {
    setSaving(true);
    try {
      const entry = await saveEntry({
        id,
        kind,
        entry_date: entryDate,
        title: overrides.title ?? title,
        content: overrides.content ?? content,
        mood: overrides.mood ?? mood,
        metadata: overrides.metadata ?? metadata,
      });
      setId(entry.id);
      setEntryDate(entry.entry_date.slice(0, 10));
      setTitle(entry.title);
      setContent(entry.content);
      setMood(entry.mood ?? null);
      setMetadata(entry.metadata ?? {});
      setEntries((previous) => [entry, ...previous.filter((row) => row.id !== entry.id)]
        .sort((a, b) => b.entry_date.localeCompare(a.entry_date) || b.updated_at.localeCompare(a.updated_at)));
    } finally {
      setSaving(false);
    }
  };

  return { id, entries, entryDate, title, setTitle, content, setContent, mood, setMood, metadata, setMetadata, saving, loaded, save, openEntry, startNew };
}

function PlanningPage({ phase, store }: { phase: boolean; store: ReturnType<typeof useStore> }) {
  const draft = useEntryDraft(phase ? "phase_plan" : "daily_plan", { content: phase ? "建立一个更稳定的学习与创作节奏。" : "" });
  const previewItems = extractPlanItems(draft.content);
  return <div className="planning-layout">
    <section className="content-card editor-card">
      <div className="card-heading"><div><span className="card-kicker">{phase ? "阶段规划" : "每日规划"}</span><h2>{phase ? "未来 90 天，我想靠近什么？" : "今天最值得推进的事项"}</h2></div><span className="soft-count">{draft.loaded ? (draft.id ? "已保存" : "新规划") : "读取中"}</span></div>
      <MarkdownEditor value={draft.content} onChange={draft.setContent} minHeight={300}
        ariaLabel={phase ? "阶段规划编辑器" : "每日规划编辑器"}
        placeholder={phase ? "写下这个阶段最想完成、体验或改变的事情…" : "用列表写下今天要做的事，每行一条；每日复盘会自动读取这些事项。"} />
      <div className="plan-item-preview">
        <div><span className="card-kicker">复盘时会读取</span><strong>{previewItems.length > 0 ? `${previewItems.length} 条事项` : "尚未形成事项"}</strong></div>
        {previewItems.length > 0 ? <ol>{previewItems.slice(0, 8).map((item) => <li key={item}>{item}</li>)}</ol> : <p>使用列表（- 事项）或直接换行书写，复盘页会按行生成勾选项。</p>}
      </div>
      <div className="editor-footer"><span>内容保存在本地 SQLite · 支持 Markdown</span><button className="green-button" onClick={() => void draft.save()} disabled={draft.saving}>{draft.saving ? "保存中…" : "保存规划"} <span>→</span></button></div>
      {draft.id ? <MemoryCaptureForm entryId={draft.id} phase={phase} store={store} /> : null}
    </section>
    <aside className="content-card side-tip"><span className="card-kicker">一个小提示</span><h3>{phase ? "目标需要方向，也需要边界。" : "计划不是待办事项的堆叠。"}</h3><p>{phase ? "写清楚：这件事为什么现在重要？完成之后，你希望自己处于什么状态？" : "如果今天只能做一件事，它会是什么？把它放在第一行，复盘时会自动成为检查项。"}</p></aside>
  </div>;
}

function ReviewPage({ phase, store }: { phase: boolean; store: ReturnType<typeof useStore> }) {
  const draft = useEntryDraft(phase ? "phase_review" : "daily_review", {});
  const [planEntry, setPlanEntry] = useState<StructuredEntry | null>(null);
  const [planLoading, setPlanLoading] = useState(true);
  const [planItems, setPlanItems] = useState<{ id: string; text: string; done: boolean }[]>([]);
  const [extras, setExtras] = useState<{ id: string; text: string; done: boolean }[]>([]);
  const [extraText, setExtraText] = useState("");
  const applied = useRef("");

  useEffect(() => {
    let alive = true;
    setPlanLoading(true);
    listEntries(phase ? "phase_plan" : "daily_plan").then((rows) => {
      if (!alive) return;
      const today = localDateKey();
      const entry = phase ? rows[0] ?? null : rows.find((row) => row.entry_date.slice(0, 10) === today) ?? null;
      setPlanEntry(entry);
      setPlanLoading(false);
    }).catch(() => { if (alive) { setPlanEntry(null); setPlanLoading(false); } });
    return () => { alive = false; };
  }, [phase]);

  useEffect(() => {
    if (!draft.loaded) return;
    const key = `${planEntry?.id ?? "none"}:${draft.id ?? "new"}:${draft.entryDate}`;
    if (applied.current === key) return;
    const savedChecks = Array.isArray(draft.metadata.checks)
      ? draft.metadata.checks.filter((item): item is { text: string; done?: boolean } => Boolean(item) && typeof (item as { text?: unknown }).text === "string")
      : [];
    const source = extractPlanItems(planEntry?.content ?? "");
    setPlanItems(source.map((text, index) => ({
      id: `plan-${index}`,
      text,
      done: Boolean(savedChecks.find((item) => item.text === text)?.done),
    })));
    const savedExtras = Array.isArray(draft.metadata.extras)
      ? draft.metadata.extras.filter((item): item is { id?: string; text: string; done?: boolean } => Boolean(item) && typeof (item as { text?: unknown }).text === "string")
      : [];
    setExtras(savedExtras.map((item, index) => ({
      id: item.id || `extra-${index}`,
      text: item.text,
      done: Boolean(item.done),
    })));
    applied.current = key;
  }, [draft.entryDate, draft.id, draft.loaded, draft.metadata, planEntry]);

  const togglePlan = (id: string) => setPlanItems((current) => current.map((item) => item.id === id ? { ...item, done: !item.done } : item));
  const toggleExtra = (id: string) => setExtras((current) => current.map((item) => item.id === id ? { ...item, done: !item.done } : item));
  const addExtra = () => {
    const text = extraText.trim();
    if (!text) return;
    setExtras((current) => [...current, { id: `extra-${Date.now()}-${current.length}`, text, done: false }]);
    setExtraText("");
  };
  const save = () => void draft.save({
    metadata: {
      planEntryId: planEntry?.id ?? null,
      checks: planItems.map(({ text, done }) => ({ text, done })),
      extras: extras.map(({ id: extraId, text, done }) => ({ id: extraId, text, done })),
    },
  });
  const checkedCount = planItems.filter((item) => item.done).length + extras.filter((item) => item.done).length;
  const totalCount = planItems.length + extras.length;

  return <div className="review-layout">
    <section className="content-card review-prompts">
      <div className="card-heading"><div><span className="card-kicker">{phase ? "阶段性复盘" : "每日复盘"}</span><h2>{phase ? "回看这段路，哪些目标真正完成了？" : "对照今天的计划，收好这一天。"}</h2></div><span className="soft-count">{draft.id ? "已保存" : "未完成"}</span></div>
      <div className="review-plan-panel">
        <div className="review-plan-heading"><div><span className="card-kicker">{phase ? "阶段计划承接" : "今日计划承接"}</span><strong>{planLoading ? "正在读取计划…" : planEntry ? `${checkedCount}/${totalCount} 条已完成` : "没有找到对应的计划"}</strong></div>{planEntry ? <span className="review-plan-source">{planEntry.entry_date.slice(0, 10)}</span> : null}</div>
        {planLoading ? <p className="state-empty">正在读取计划事项…</p> : planItems.length === 0 ? <p className="review-empty">计划中还没有可读取的事项。可以先在规划页用列表写下计划，也可以直接在下面添加。</p> : (
          <div className="review-check-list">
            {planItems.map((item) => <label key={item.id} className={`review-check ${item.done ? "done" : ""}`}>
              <input type="checkbox" checked={item.done} onChange={() => togglePlan(item.id)} />
              <span className="review-check-box" aria-hidden="true">{item.done ? "✓" : ""}</span>
              <span>{item.text}</span>
            </label>)}
          </div>
        )}
        <div className="review-add-row">
          <input value={extraText} onChange={(event) => setExtraText(event.target.value)} placeholder="补充一件计划外的事…" onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addExtra(); } }} />
          <button type="button" className="subtle-button" onClick={addExtra}>＋ 添加</button>
        </div>
        {extras.length > 0 ? <div className="review-check-list extras">
          {extras.map((item) => <div key={item.id} className={`review-check extra ${item.done ? "done" : ""}`}>
            <label><input type="checkbox" checked={item.done} onChange={() => toggleExtra(item.id)} /><span className="review-check-box" aria-hidden="true">{item.done ? "✓" : ""}</span><span>{item.text}</span></label>
            <button type="button" aria-label={`删除 ${item.text}`} onClick={() => setExtras((current) => current.filter((row) => row.id !== item.id))}>×</button>
          </div>)}
        </div> : null}
      </div>
      <div className="review-editor-section"><span className="card-kicker">自由复盘</span><MarkdownEditor value={draft.content} onChange={draft.setContent} minHeight={240} ariaLabel={phase ? "阶段复盘编辑器" : "每日复盘编辑器"} placeholder="写下今天发生了什么、有什么发现，以及明天想怎样继续…" /></div>
      <div className="review-actions"><span className="editor-note">勾选与文字会一起保存到本地 SQLite。</span><button className="green-button" onClick={save} disabled={draft.saving}>{draft.saving ? "保存中…" : "完成复盘"} <span>→</span></button></div>
      {draft.id ? <MemoryCaptureForm entryId={draft.id} phase={phase} store={store} /> : null}
    </section>
    <aside className="content-card side-tip"><span className="card-kicker">复盘不是审判</span><h3>诚实，但不要苛刻。</h3><p>记录不是为了证明自己做得够不够好，而是让下一次选择多一点依据。</p></aside>
  </div>;
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
      setMessage(result.status === "candidate" ? "已提交为待审核候选，后续审核入口接入后会通知你。" : "这条来源修订已处理过，未重复创建候选。");
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

function FeedbackPage() { const draft = useEntryDraft("feedback", {}); const [category, setCategory] = useState("使用感受"); return <div className="feedback-layout"><section className="content-card feedback-main"><span className="card-kicker">写给 LifeOS</span><h2>哪里让你觉得顺手？哪里还不够像你？</h2><textarea className="feedback-editor" placeholder="可以是一句话，也可以是一段具体的经历…" value={draft.content} onChange={(event) => draft.setContent(event.target.value)} /><div className="feedback-tags">{["功能建议", "使用感受", "发现问题", "其他"].map((tag) => <button className={category === tag ? "selected" : ""} key={tag} onClick={() => setCategory(tag)}>{tag}</button>)}</div><button className="green-button" onClick={() => void draft.save({ metadata: { category } })} disabled={draft.saving}>{draft.saving ? "提交中…" : "提交反馈"} <span>→</span></button></section><section className="content-card feedback-history"><div className="card-heading"><div><span className="card-kicker">你的声音</span><h2>最近反馈</h2></div><span className="soft-count">来自 SQLite</span></div>{draft.content ? <div className="feedback-note"><span>✓</span><div><strong>{draft.content.slice(0, 24)}{draft.content.length > 24 ? "…" : ""}</strong><small>刚刚 · 已保存</small></div></div> : <div className="state-empty">还没有新的反馈</div>}</section></div>; }

function DiaryPage() {
  const draft = useEntryDraft("diary", {});
  const moods = ["☀ 平静", "☁ 有点累", "✦ 充满能量", "♡ 说不清"];
  return <div className="diary-layout">
    <section className="content-card diary-editor">
      <div className="card-heading"><div><span className="card-kicker">{draft.id ? "编辑日记" : "今天 · 私人记录"}</span><h2>{draft.id ? "正在回看一篇旧日记" : "今天的日记"}</h2></div><span className="soft-count">{draft.id ? "已保存" : "新记录"}</span></div>
      <MarkdownEditor value={draft.content} onChange={draft.setContent} minHeight={340} ariaLabel="日记编辑器" placeholder="今天有什么值得被写下来？支持 Markdown 标题、列表、引用和代码块。" />
      <div className="diary-mood"><span>今天的心情</span>{moods.map((mood) => <button className={draft.mood === mood ? "selected" : ""} key={mood} onClick={() => draft.setMood(mood)}>{mood}</button>)}</div>
      <div className="editor-footer"><span>内容与心情会保存到本地 SQLite</span><button className="green-button" onClick={() => void draft.save()} disabled={draft.saving}>{draft.saving ? "保存中…" : "保存日记"} <span>→</span></button></div>
    </section>
    <EntryHistory entries={draft.entries} activeId={draft.id} onSelect={draft.openEntry} onNew={draft.startNew} kicker="历史日记" heading="往日的记录" />
  </div>;
}

function InsightPage() {
  const draft = useEntryDraft("insight", {});
  return <div className="insight-layout">
    <section className="content-card insight-editor">
      <div className="card-heading"><div><span className="card-kicker">心得 / 体验</span><h2>{draft.id ? "继续整理这份心得" : "记录一个正在发酵的想法"}</h2></div><span className="soft-count">{draft.id ? "已保存" : "新记录"}</span></div>
      <input className="insight-title" placeholder="先写一个标题…" value={draft.title} onChange={(event) => draft.setTitle(event.target.value)} />
      <MarkdownEditor value={draft.content} onChange={draft.setContent} minHeight={300} ariaLabel="心得体验编辑器" placeholder="一段阅读后的感受、一次旅途中的发现，或者一个你不想忘记的瞬间…" />
      <div className="editor-footer"><span>内容会保存到本地 SQLite</span><button className="green-button" onClick={() => void draft.save()} disabled={draft.saving}>{draft.saving ? "保存中…" : "保存心得"} <span>→</span></button></div>
    </section>
    <EntryHistory entries={draft.entries} activeId={draft.id} onSelect={draft.openEntry} onNew={draft.startNew} kicker="历史心得" heading="知识花园" />
  </div>;
}
