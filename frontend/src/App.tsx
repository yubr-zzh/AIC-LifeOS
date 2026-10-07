import { useEffect, useState } from "react";
import { useStore } from "./state/store";
import { ChatPanel } from "./panels/ChatPanel";
import { RuntimeRail } from "./panels/RuntimeRail";
import { EventsPanel } from "./panels/EventsPanel";
import { MemoryPanel } from "./panels/MemoryPanel";
import { TracePanel } from "./panels/TracePanel";
import { SkillsPanel } from "./panels/SkillsPanel";
import { PermissionsPanel } from "./panels/PermissionsPanel";
import { DataFlowView } from "./panels/DataFlowView";
import { ConversationHistory } from "./panels/ConversationHistory";
import { LoginDialog } from "./panels/LoginDialog";
import type { LocalUser } from "./panels/LoginDialog";
import { SettingsPage } from "./panels/SettingsPage";
import { listEntries, proposeEntryMemoryCandidate, saveEntry } from "./api/client";
import type { MemoryScope, StructuredEntry, StructuredEntryKind } from "./api/types";
import { DiaryPage, FeedbackPage, InsightPage } from "./panels/StructuredPages";
import { IconBook, IconBolt, IconCalendar, IconHistory, IconHome, IconMessage, IconPlus, IconSettings, IconSpark, IconSun, IconUser } from "./components/Icons";
import { WorkCalendar } from "./components/WorkCalendar";

type SectionId =
  | "home"
  | "daily-plan"
  | "daily-review"
  | "phase-plan"
  | "phase-review"
  | "chat"
  | "feedback"
  | "diary"
  | "insight"
  | "memory"
  | "plans"
  | "records"
  | "settings"
  | "admin";

type NavIcon = "home" | "message" | "calendar" | "book" | "spark";
const navigation: { group: string; items: { id: SectionId; label: string; icon: NavIcon; hint?: string }[] }[] = [
  {
    group: "我的生活",
    items: [
      { id: "home", label: "今天", icon: "home" },
      { id: "chat", label: "和 LifeOS 聊聊", icon: "message" },
      { id: "plans", label: "计划", icon: "calendar", hint: "安排今天或看看阶段方向" },
      { id: "records", label: "记录", icon: "book", hint: "日记、心得和回顾" },
    ],
  },
];

const sectionMeta: Record<SectionId, { eyebrow: string; title: string; description: string }> = {
  home: { eyebrow: "工作台 · 今日概览", title: "今天，先照顾最重要的事", description: "把计划变成行动，把行动留下痕迹。" },
  "daily-plan": { eyebrow: "计划 · 每日", title: "给今天一个清晰的起点", description: "不追求塞满日程，只选择真正值得推进的三件事。" },
  "daily-review": { eyebrow: "复盘 · 每日", title: "把今天温柔地收好", description: "记录发生过什么，也看见自己做得好的地方。" },
  "phase-plan": { eyebrow: "计划 · 阶段", title: "把远方拆成下一步", description: "阶段性目标不必宏大，但需要可以被看见、被推进。" },
  "phase-review": { eyebrow: "复盘 · 阶段", title: "重新校准你的方向", description: "回看过去一段时间，判断什么值得继续，什么应该放下。" },
  chat: { eyebrow: "随时聊聊", title: "和 LifeOS 聊聊", description: "计划、学习、项目进展，或任何想记下来的念头。" },
  feedback: { eyebrow: "系统 · 反馈", title: "让 LifeOS 越来越懂你", description: "告诉我们哪里顺手，哪里还可以更贴近你的工作方式。" },
  diary: { eyebrow: "记录 · 日记", title: "给今天留一页空白", description: "不必写得完整，想到什么就从哪里开始。" },
  insight: { eyebrow: "沉淀 · 心得 / 体验", title: "把经历变成自己的东西", description: "记录一个念头、一种感受，或者一次值得记住的体验。" },
  settings: { eyebrow: "系统 · 设置", title: "把 LifeOS 调到适合你的状态", description: "管理外观、模型与 Agent、Memory、通知和数据边界。" },
  admin: { eyebrow: "后台 · 系统", title: "LifeOS 的运行后台", description: "这里放置事件、记忆、技能与运行状态等工程信息。" },
  memory: { eyebrow: "我的记忆", title: "LifeOS 目前记住了什么？", description: "你可以查看、修正和撤回这些长期认知。" },
  plans: { eyebrow: "我的计划", title: "给重要的事留出位置", description: "安排今天，也时常看看自己正走向哪里。" },
  records: { eyebrow: "我的记录", title: "把今天留下来", description: "写下经历、想法和回望，让重要的事以后还能找到。" },
};

function NavIconGlyph({ name }: { name: NavIcon }) {
  if (name === "home") return <IconHome size={17} />;
  if (name === "message") return <IconMessage size={17} />;
  if (name === "calendar") return <IconCalendar size={17} />;
  if (name === "book") return <IconBook size={17} />;
  return <IconSpark size={17} />;
}

const SECTION_IDS = new Set<SectionId>([
  "home", "daily-plan", "daily-review", "phase-plan", "phase-review", "chat",
  "feedback", "diary", "insight", "memory", "plans", "records", "settings", "admin",
]);

function isNavItemActive(item: SectionId, active: SectionId) {
  if (item === "plans") return ["plans", "daily-plan", "daily-review", "phase-plan", "phase-review"].includes(active);
  if (item === "records") return ["records", "diary", "insight", "feedback"].includes(active);
  return item === active;
}

function sectionFromLocation(): SectionId {
  const value = window.location.hash.replace(/^#/, "") as SectionId;
  return SECTION_IDS.has(value) ? value : "home";
}

function loadLocalUser(): LocalUser | null {
  try {
    const raw = window.localStorage.getItem("lifeos-local-user");
    return raw ? JSON.parse(raw) as LocalUser : null;
  } catch {
    return null;
  }
}

export default function App() {
  const store = useStore();
  const [active, setActive] = useState<SectionId>(() => sectionFromLocation());
  const [dark, setDark] = useState(false);
  const [loginOpen, setLoginOpen] = useState(() => window.location.hash === "#login");
  const [user, setUser] = useState<LocalUser | null>(() => loadLocalUser());
  const userInitial = user?.name?.slice(0, 1).toUpperCase() || "Z";
  const meta = sectionMeta[active];
  const dateParts = new Intl.DateTimeFormat("zh-CN", { day: "numeric", month: "long" }).formatToParts(new Date());
  const todayDay = dateParts.find((part) => part.type === "day")?.value ?? "";
  const todayMonth = dateParts.find((part) => part.type === "month")?.value ?? "";

  const select = (id: SectionId) => {
    setActive(id);
    if (window.location.hash !== `#${id}`) window.history.replaceState(null, "", `#${id}`);
  };

  useEffect(() => {
    const onHashChange = () => {
      if (window.location.hash === "#login") {
        setLoginOpen(true);
        return;
      }
      setActive(sectionFromLocation());
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const signedIn = (nextUser: LocalUser) => {
    setUser(nextUser);
    setLoginOpen(false);
    try {
      window.localStorage.setItem("lifeos-local-user", JSON.stringify(nextUser));
    } catch {
      // Login is still valid for the current session.
    }
  };

  return (
    <div className={`lifeos-shell ${dark ? "theme-night" : ""}${active === "chat" ? " chat-active" : ""}`}>
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <aside className="side-nav">
        <div className="brand-block">
          <div className="brand-mark"><IconBolt size={17} /></div>
          <div>
            <div className="brand-name">LifeOS</div>
            <div className="brand-caption">AI 助手 · 计划 · 记忆</div>
          </div>
        </div>

        <nav className="main-nav" aria-label="主导航">
          {navigation.map((group) => (
            <div className="nav-group" key={group.group}>
              <div className="nav-group-title">{group.group}</div>
              {group.items.map((item) => (
                <button
                  key={item.id}
                  className={`nav-item ${isNavItemActive(item.id, active) ? "active" : ""}`}
                  onClick={() => select(item.id)}
                  aria-current={isNavItemActive(item.id, active) ? "page" : undefined}
                  title={item.hint}
                >
                  <span className="nav-icon" aria-hidden="true"><NavIconGlyph name={item.icon} /></span>
                  <span className="nav-label">{item.label}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>

        <div className="memory-nav-link">
          <button
            type="button"
            className={`nav-item ${active === "memory" ? "active" : ""}`}
            onClick={() => select("memory")}
            aria-current={active === "memory" ? "page" : undefined}
          >
            <span className="nav-icon" aria-hidden="true"><NavIconGlyph name="book" /></span>
            <span className="nav-label">我的记忆</span>
          </button>
        </div>

        <div className="side-footer">
          <button
            type="button"
            className={`side-settings-button ${active === "settings" ? "active" : ""}`}
            onClick={() => select("settings")}
          >
            <IconSettings size={16} />
            <span>设置</span>
          </button>
        </div>
      </aside>

      <div className="content-shell">
        <header className="workspace-header">
          <div className="breadcrumb"><span>LifeOS</span><i>/</i><strong>{meta.eyebrow.split(" · ")[0]}</strong></div>
          <div className="header-actions">
            <button className="header-icon-button" onClick={() => setDark(!dark)} title="切换主题" aria-label={`切换到${dark ? "浅色" : "夜间"}主题`} aria-pressed={dark}>{dark ? <IconSun size={16} /> : <IconSpark size={16} />}</button>
            <button className="header-icon-button" onClick={() => select("settings")} title="设置" aria-label="设置"><IconSettings size={16} /></button>
            <button className="avatar avatar-button" onClick={() => setLoginOpen(true)} title={user ? `${user.name} · 账户` : "登录 LifeOS"} aria-label="打开账户与登录">
              {userInitial}
            </button>
          </div>
        </header>

        <main id="main-content" className={`workspace-main${active === "chat" ? " chat-workspace-main" : ""}`}>
          <div className="page-intro">
            <div>
              <div className="page-eyebrow">{meta.eyebrow}</div>
              <h1>{meta.title}</h1>
              <p>{meta.description}</p>
            </div>
            <div className="intro-date"><span>今天</span><strong>{todayDay}</strong><small>{todayMonth}</small></div>
          </div>
          <SectionContent active={active} store={store} onNavigate={select} dark={dark} onDarkChange={setDark} />
        </main>
      </div>
      <LoginDialog open={loginOpen} onClose={() => setLoginOpen(false)} onSignedIn={signedIn} />
    </div>
  );
}

function SectionContent({ active, store, onNavigate, dark, onDarkChange }: { active: SectionId; store: ReturnType<typeof useStore>; onNavigate: (id: SectionId) => void; dark: boolean; onDarkChange: (value: boolean) => void }) {
  if (active === "chat") {
    return <ChatWorkspace store={store} onOpenPlanning={() => onNavigate("phase-plan")} />;
  }
  if (active === "memory") return <div className="memory-page"><MemoryPanel store={store} /></div>;
  if (active === "settings") return <SettingsPage store={store} dark={dark} onDarkChange={onDarkChange} onOpenDiagnostics={() => onNavigate("admin")} />;
  if (active === "admin") return <AdminPage store={store} />;
  if (["plans", "daily-plan", "daily-review", "phase-plan", "phase-review"].includes(active)) {
    return <PlanHub active={active} store={store} onNavigate={onNavigate} />;
  }
  if (["records", "diary", "insight", "feedback"].includes(active)) {
    return <RecordsHub active={active} store={store} onNavigate={onNavigate} />;
  }
  return <HomePage onNavigate={onNavigate} />;
}

function ChatWorkspace({ store, onOpenPlanning }: { store: ReturnType<typeof useStore>; onOpenPlanning: () => void }) {
  const [historyOpen, setHistoryOpen] = useState(false);
  useEffect(() => {
    if (!historyOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setHistoryOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [historyOpen]);
  const conversation = store.activeConversation;
  const title = conversation?.title === "新的对话" ? "新对话" : conversation?.title || "新对话";
  return <div className={`chat-workspace${historyOpen ? " history-open" : ""}`}>
    {historyOpen ? <button type="button" className="chat-history-backdrop" aria-label="关闭对话历史" onClick={() => setHistoryOpen(false)} /> : null}
    <ConversationHistory store={store} mobileOpen={historyOpen} onClose={() => setHistoryOpen(false)} />
    <div className="chat-page-grid">
      <section className="content-card chat-card">
        <div className="chat-room-header">
          <div className="chat-room-title"><span>当前对话</span><h2>{title}</h2></div>
          <div className="chat-mobile-actions">
            <button type="button" className="chat-mobile-history" onClick={() => setHistoryOpen(true)} aria-label="打开对话历史" aria-controls="conversation-history" aria-expanded={historyOpen}><IconHistory size={17} /><span>历史</span></button>
            <button type="button" className="chat-mobile-new" onClick={() => store.createConversation()}><IconPlus size={16} /><span>新对话</span></button>
          </div>
        </div>
        <ChatPanel store={store} onOpenPlanning={onOpenPlanning} />
      </section>
    </div>
  </div>;
}

function PlanHub({ active, store, onNavigate }: { active: SectionId; store: ReturnType<typeof useStore>; onNavigate: (id: SectionId) => void }) {
  const phase = active === "phase-plan" || active === "phase-review";
  const reviewing = active === "daily-review" || active === "phase-review";
  return <div className="hub-page">
    <div className="hub-switch-row">
      <div className="hub-tabs" role="group" aria-label="计划周期">
        <button type="button" className={!phase ? "selected" : ""} onClick={() => onNavigate(reviewing ? "daily-review" : "daily-plan")}>今天</button>
        <button type="button" className={phase ? "selected" : ""} onClick={() => onNavigate(reviewing ? "phase-review" : "phase-plan")}>阶段方向</button>
      </div>
      <div className="hub-tabs" role="group" aria-label="计划或回顾">
        <button type="button" className={!reviewing ? "selected" : ""} onClick={() => onNavigate(phase ? "phase-plan" : "daily-plan")}>做计划</button>
        <button type="button" className={reviewing ? "selected" : ""} onClick={() => onNavigate(phase ? "phase-review" : "daily-review")}>回顾一下</button>
      </div>
    </div>
    {reviewing ? <ReviewPage phase={phase} store={store} /> : <PlanningPage phase={phase} store={store} />}
  </div>;
}

function RecordsHub({ active, store, onNavigate }: { active: SectionId; store: ReturnType<typeof useStore>; onNavigate: (id: SectionId) => void }) {
  const [showCalendar, setShowCalendar] = useState(false);
  const view = active === "insight" ? "insight" : active === "feedback" ? "feedback" : "diary";
  return <div className="hub-page">
    <div className="hub-switch-row">
      <div className="hub-tabs" role="group" aria-label="记录类型">
        <button type="button" className={!showCalendar && view === "diary" ? "selected" : ""} onClick={() => { setShowCalendar(false); onNavigate("diary"); }}>日记</button>
        <button type="button" className={!showCalendar && view === "insight" ? "selected" : ""} onClick={() => { setShowCalendar(false); onNavigate("insight"); }}>心得</button>
        <button type="button" className={!showCalendar && view === "feedback" ? "selected" : ""} onClick={() => { setShowCalendar(false); onNavigate("feedback"); }}>给 LifeOS 的反馈</button>
        <button type="button" className={showCalendar ? "selected" : ""} onClick={() => setShowCalendar(true)}>回看记录</button>
      </div>
    </div>
    {showCalendar ? <WorkCalendar onNavigate={onNavigate} /> : view === "insight" ? <InsightPage /> : view === "feedback" ? <FeedbackPage /> : <DiaryPage />}
  </div>;
}

function HomePage({ onNavigate }: { onNavigate: (id: SectionId) => void }) {
  const [entries, setEntries] = useState<StructuredEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const now = new Date();
  const todayKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  useEffect(() => {
    let current = true;
    Promise.all(["daily_plan", "daily_review", "phase_plan", "phase_review", "diary", "insight"].map((kind) =>
      listEntries(kind as StructuredEntryKind, { limit: 20 }),
    )).then((batches) => {
      if (current) setEntries(batches.flat().sort((a, b) => b.updated_at.localeCompare(a.updated_at)));
    }).catch(() => {
      if (current) setLoadFailed(true);
    }).finally(() => {
      if (current) setLoading(false);
    });
    return () => { current = false; };
  }, []);
  const todayPlan = entries.find((entry) => entry.kind === "daily_plan" && entry.entry_date === todayKey);
  const recent = entries.slice(0, 3);
  const excerpt = (entry: StructuredEntry) => entry.content.trim().replace(/\s+/g, " ").slice(0, 150);
  const entryLabel: Record<StructuredEntryKind, string> = {
    daily_plan: "今日计划", daily_review: "今日回顾", phase_plan: "阶段方向",
    phase_review: "阶段回顾", diary: "日记", insight: "心得", feedback: "反馈",
  };
  const todayLabel = new Intl.DateTimeFormat("zh-CN", { weekday: "short", month: "long", day: "numeric" }).format(now);
  return <div className="home-user-page">
    <section className="home-welcome content-card">
      <span className="card-kicker">{todayLabel}</span>
      <h2>今天，想从哪件事开始？</h2>
      <p>聊聊你的计划、正在想的事，或者刚刚发生的经历。</p>
      <div className="home-actions">
        <button className="green-button" onClick={() => onNavigate("chat")}>和 LifeOS 聊聊 <span>→</span></button>
        <button className="text-button" onClick={() => onNavigate("plans")}>先写下今天的计划</button>
      </div>
    </section>
    <section className="home-today content-card">
      <div className="card-heading"><div><span className="card-kicker">留给今天</span><h2>今天的计划</h2></div><button className="text-button" onClick={() => onNavigate("plans")}>{todayPlan ? "继续整理" : "写一写"} →</button></div>
      {loading ? <p role="status">正在找回今天的记录…</p> : todayPlan ? <p className="home-entry-excerpt">{excerpt(todayPlan) || "计划已保存，可以继续补充内容。"}</p> : <div className="home-empty"><p>{loadFailed ? "暂时没能读取记录。你仍可以直接开始聊天或写下计划。" : "还没有今天的计划。给最重要的一件事留个位置就好。"}</p><button className="green-button" onClick={() => onNavigate("plans")}>写下今天的计划 <span>→</span></button></div>}
    </section>
    <section className="home-recent content-card">
      <div className="card-heading"><div><span className="card-kicker">慢慢积累</span><h2>最近留下的记录</h2></div><button className="text-button" onClick={() => onNavigate("records")}>去记录 →</button></div>
      {loading ? <p role="status">正在读取…</p> : recent.length ? recent.map((entry) => <button type="button" className="home-record-row" key={entry.id} onClick={() => onNavigate(entry.kind === "daily_plan" ? "daily-plan" : entry.kind === "daily_review" ? "daily-review" : entry.kind === "phase_plan" ? "phase-plan" : entry.kind === "phase_review" ? "phase-review" : entry.kind === "insight" ? "insight" : "diary")}><span className="home-record-kind">{entryLabel[entry.kind]}</span><span className="home-record-text">{entry.title || excerpt(entry) || "打开这条记录"}</span><time>{entry.entry_date}</time></button>) : <div className="home-empty"><p>{loadFailed ? "记录暂时不可用。" : "这里会慢慢出现你的计划、回顾和日记。"}</p><button className="text-button" onClick={() => onNavigate("records")}>开始记录 →</button></div>}
    </section>
  </div>;
}

function useEntryDraft(kind: StructuredEntryKind, initial: { title?: string; content?: string }) {
  const [id, setId] = useState<string>();
  const [title, setTitle] = useState(initial.title ?? "");
  const [content, setContent] = useState(initial.content ?? "");
  const [mood, setMood] = useState<string | null>(null);
  const [metadata, setMetadata] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    listEntries(kind).then((entries) => {
      if (!alive || !entries[0]) { if (alive) setLoaded(true); return; }
      const entry = entries[0];
      setId(entry.id); setTitle(entry.title); setContent(entry.content);
      setMood(entry.mood ?? null); setMetadata(entry.metadata ?? {}); setLoaded(true);
    }).catch(() => setLoaded(true));
    return () => { alive = false; };
  }, [kind]);

  const save = async (overrides: Partial<{ title: string; content: string; mood: string | null; metadata: Record<string, unknown> }> = {}) => {
    setSaving(true);
    try {
      const now = new Date();
      const entryDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
      const entry = await saveEntry({ id, kind, entry_date: entryDate, title: overrides.title ?? title, content: overrides.content ?? content, mood: overrides.mood ?? mood, metadata: overrides.metadata ?? metadata });
      setId(entry.id); setTitle(entry.title); setContent(entry.content); setMood(entry.mood ?? null); setMetadata(entry.metadata ?? {});
    } finally { setSaving(false); }
  };
  return { id, title, setTitle, content, setContent, mood, setMood, metadata, setMetadata, saving, loaded, save };
}

function PlanningPage({ phase, store }: { phase: boolean; store: ReturnType<typeof useStore> }) {
  const draft = useEntryDraft(phase ? "phase_plan" : "daily_plan", { content: phase ? "建立一个更稳定的学习与创作节奏。" : "" });
  return <div className="planning-layout"><section className="content-card editor-card"><div className="card-heading"><div><span className="card-kicker">{phase ? "阶段规划" : "今日规划"}</span><h2>{phase ? "未来 90 天，我想靠近什么？" : "今天最值得推进的三件事"}</h2></div><span className="soft-count">{draft.loaded ? (draft.id ? "已保存" : "新规划") : "读取中"}</span></div><textarea className="big-editor" placeholder={phase ? "写下这个阶段最想完成、体验或改变的事情…" : "从最重要的事情开始，不必一次写完…"} value={draft.content} onChange={(event) => draft.setContent(event.target.value)} /><div className="editor-footer"><span>保存后可随时回看和修改</span><button className="green-button" onClick={() => void draft.save()} disabled={draft.saving}>{draft.saving ? "保存中…" : "保存规划"} <span>→</span></button></div>{draft.id ? <MemoryCaptureForm entryId={draft.id} phase={phase} store={store} /> : null}</section><aside className="content-card side-tip"><span className="card-kicker">一个小提示</span><h3>{phase ? "目标需要方向，也需要边界。" : "计划不是待办事项的堆叠。"}</h3><p>{phase ? "试着写清楚：这件事为什么现在重要？完成之后，你希望自己处于什么状态？" : "如果今天只能做一件事，它会是什么？先把这一件事放在最前面。"}</p></aside></div>;
}

function ReviewPage({ phase, store }: { phase: boolean; store: ReturnType<typeof useStore> }) {
  const questions = phase ? ["这段时间，什么真正带来了进展？", "什么消耗了你，却没有带来相应的回报？", "下一阶段，你要继续、停止或开始什么？"] : ["今天最有能量的时刻是什么？", "有什么事情没有完成？真正的原因是什么？", "明天醒来后，你最想先做什么？"];
  const draft = useEntryDraft(phase ? "phase_review" : "daily_review", {});
  const [answers, setAnswers] = useState<string[]>(["", "", ""]);
  useEffect(() => { const saved = draft.metadata.answers; if (Array.isArray(saved)) setAnswers(saved.map(String)); }, [draft.metadata]);
  const save = () => void draft.save({ content: JSON.stringify({ answers }), metadata: { answers } });
  return <div className="review-layout"><section className="content-card review-prompts"><div className="card-heading"><div><span className="card-kicker">{phase ? "阶段性复盘" : "每日复盘"}</span><h2>{phase ? "回看这段路，你发现了什么？" : "今天发生了什么？"}</h2></div><span className="soft-count">{draft.id ? "已保存" : "未完成"}</span></div>{questions.map((question, index) => <label className="prompt-block" key={question}><span>{question}</span><textarea placeholder="写下你的想法…" value={answers[index]} onChange={(event) => setAnswers((current) => current.map((value, position) => position === index ? event.target.value : value))} /></label>)}<button className="green-button" onClick={save} disabled={draft.saving}>{draft.saving ? "保存中…" : "完成复盘"} <span>→</span></button>{draft.id ? <MemoryCaptureForm entryId={draft.id} phase={phase} store={store} /> : null}</section><aside className="content-card review-aside"><span className="card-kicker">复盘不是审判</span><div className="big-emoji">☁</div><h3>诚实，但不要苛刻。</h3><p>记录不是为了证明自己做得够不够好，而是让下一次选择多一点依据。</p></aside></div>;
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

function AdminPage({ store }: { store: ReturnType<typeof useStore> }) { return <div className="admin-page"><div className="admin-banner"><div><span className="card-kicker">系统后台</span><h2>工程信息集中在这里</h2><p>普通使用页面保持安静。只有进入后台，才会看到 Agent、事件、记忆和 Trace 等运行细节。</p></div><span className="admin-badge">开发者视图</span></div><div className="admin-flow"><DataFlowView store={store} /></div><div className="admin-grid"><RuntimeRail store={store} /><EventsPanel store={store} /><MemoryPanel store={store} /><SkillsPanel store={store} /><PermissionsPanel store={store} /><TracePanel store={store} /></div></div>; }
