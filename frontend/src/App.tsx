import { useEffect, useMemo, useState } from "react";
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
import type { MemoryScope, StructuredEntryKind } from "./api/types";
import { DiaryPage, FeedbackPage, InsightPage } from "./panels/StructuredPages";
import { IconBook, IconBolt, IconCalendar, IconHistory, IconHome, IconMessage, IconSettings, IconSpark, IconSun, IconUser } from "./components/Icons";
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
  | "settings"
  | "admin";

type NavIcon = "home" | "message" | "calendar" | "book" | "spark";
const navigation: { group: string; items: { id: SectionId; label: string; icon: NavIcon; hint?: string }[] }[] = [
  {
    group: "工作台",
    items: [
      { id: "home", label: "今日概览", icon: "home" },
      { id: "chat", label: "对话", icon: "message", hint: "与 LifeOS 对话" },
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
    group: "系统",
    items: [{ id: "admin", label: "系统后台", icon: "spark", hint: "工程与运行状态" }],
  },
];

const sectionMeta: Record<SectionId, { eyebrow: string; title: string; description: string }> = {
  home: { eyebrow: "工作台 · 今日概览", title: "今天，先照顾最重要的事", description: "把计划变成行动，把行动留下痕迹。" },
  "daily-plan": { eyebrow: "计划 · 每日", title: "给今天一个清晰的起点", description: "不追求塞满日程，只选择真正值得推进的三件事。" },
  "daily-review": { eyebrow: "复盘 · 每日", title: "把今天温柔地收好", description: "记录发生过什么，也看见自己做得好的地方。" },
  "phase-plan": { eyebrow: "计划 · 阶段", title: "把远方拆成下一步", description: "阶段性目标不必宏大，但需要可以被看见、被推进。" },
  "phase-review": { eyebrow: "复盘 · 阶段", title: "重新校准你的方向", description: "回看过去一段时间，判断什么值得继续，什么应该放下。" },
  chat: { eyebrow: "连接 · 对话", title: "和你的第二大脑聊聊", description: "LifeOS 会记住重要的上下文，陪你把想法变成下一步。" },
  feedback: { eyebrow: "系统 · 反馈", title: "让 LifeOS 越来越懂你", description: "告诉我们哪里顺手，哪里还可以更贴近你的工作方式。" },
  diary: { eyebrow: "记录 · 日记", title: "给今天留一页空白", description: "不必写得完整，想到什么就从哪里开始。" },
  insight: { eyebrow: "沉淀 · 心得 / 体验", title: "把经历变成自己的东西", description: "记录一个念头、一种感受，或者一次值得记住的体验。" },
  settings: { eyebrow: "系统 · 设置", title: "把 LifeOS 调到适合你的状态", description: "管理外观、模型与 Agent、Memory、通知和数据边界。" },
  admin: { eyebrow: "后台 · 系统", title: "LifeOS 的运行后台", description: "这里放置事件、记忆、技能与运行状态等工程信息。" },
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
  "feedback", "diary", "insight", "settings", "admin",
]);

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
            <div className="brand-caption">本地仓库 · 个人操作系统</div>
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
                  {item.id === "daily-review" ? <span className="nav-dot" /> : null}
                </button>
              ))}
            </div>
          ))}
        </nav>

        <div className="side-footer">
          <button
            type="button"
            className={`side-settings-button ${active === "settings" ? "active" : ""}`}
            onClick={() => select("settings")}
          >
            <IconSettings size={16} />
            <span>设置</span>
          </button>
          <div className="side-footer-line"><span className="status-orb" />系统运行良好</div>
          <div className="side-footer-sub">Markdown · 本地 SQLite · 已连接</div>
        </div>
      </aside>

      <div className="content-shell">
        <header className="workspace-header">
          <div className="breadcrumb"><span>LifeOS</span><i>/</i><strong>{meta.eyebrow.split(" · ")[0]}</strong></div>
          <div className="header-actions">
            <span className="sync-label"><span className="status-orb" />本地仓库 · 刚刚同步</span>
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
    return (
      <div className="chat-workspace">
        <ConversationHistory store={store} />
        <div className="chat-page-grid">
          <section className="content-card chat-card">
            <div className="card-heading">
              <div><span className="card-kicker"><IconHistory size={12} /> 实时连接</span><h2>对话空间</h2></div>
              <span className="live-chip"><span className="status-orb" />在线</span>
            </div>
            <ChatPanel store={store} onOpenPlanning={() => onNavigate("phase-plan")} />
          </section>
          <RuntimeRail store={store} />
        </div>
      </div>
    );
  }
  if (active === "feedback") return <FeedbackPage />;
  if (active === "diary") return <DiaryPage />;
  if (active === "insight") return <InsightPage />;
  if (active === "settings") return <SettingsPage store={store} dark={dark} onDarkChange={onDarkChange} />;
  if (active === "admin") return <AdminPage store={store} />;
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
    <WorkCalendar onNavigate={onNavigate} />
    <section className="content-card quote-card"><span className="quote-mark">“</span><p>真正重要的不是把每件事都做好，而是知道此刻什么值得被做好。</p><span className="quote-source">— 今日提醒</span></section>
    <section className="content-card recent-card"><div className="card-heading"><div><span className="card-kicker">最近记录</span><h2>工作台动态</h2></div><button className="text-button" onClick={() => onNavigate("feedback")}>查看全部</button></div><div className="recent-row"><span className="recent-icon">↗</span><div><strong>完成了一次对话</strong><small>刚刚 · 已写入事件队列</small></div><span className="recent-status">已记录</span></div><div className="recent-row"><span className="recent-icon">✦</span><div><strong>收到一个新的反馈</strong><small>昨天 · 关于复盘流程</small></div><span className="recent-status">待处理</span></div></section>
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
      const entry = await saveEntry({ id, kind, entry_date: new Date().toISOString().slice(0, 10), title: overrides.title ?? title, content: overrides.content ?? content, mood: overrides.mood ?? mood, metadata: overrides.metadata ?? metadata });
      setId(entry.id); setTitle(entry.title); setContent(entry.content); setMood(entry.mood ?? null); setMetadata(entry.metadata ?? {});
    } finally { setSaving(false); }
  };
  return { id, title, setTitle, content, setContent, mood, setMood, metadata, setMetadata, saving, loaded, save };
}

function PlanningPage({ phase, store }: { phase: boolean; store: ReturnType<typeof useStore> }) {
  const draft = useEntryDraft(phase ? "phase_plan" : "daily_plan", { content: phase ? "建立一个更稳定的学习与创作节奏。" : "" });
  return <div className="planning-layout"><section className="content-card editor-card"><div className="card-heading"><div><span className="card-kicker">{phase ? "阶段规划" : "今日规划"}</span><h2>{phase ? "未来 90 天，我想靠近什么？" : "今天最值得推进的三件事"}</h2></div><span className="soft-count">{draft.loaded ? (draft.id ? "已保存" : "新规划") : "读取中"}</span></div><textarea className="big-editor" placeholder={phase ? "写下这个阶段最想完成、体验或改变的事情…" : "从最重要的事情开始，不必一次写完…"} value={draft.content} onChange={(event) => draft.setContent(event.target.value)} /><div className="editor-footer"><span>内容会保存到本地 SQLite</span><button className="green-button" onClick={() => void draft.save()} disabled={draft.saving}>{draft.saving ? "保存中…" : "保存规划"} <span>→</span></button></div>{draft.id ? <MemoryCaptureForm entryId={draft.id} phase={phase} store={store} /> : null}</section><aside className="content-card side-tip"><span className="card-kicker">一个小提示</span><h3>{phase ? "目标需要方向，也需要边界。" : "计划不是待办事项的堆叠。"}</h3><p>{phase ? "试着写清楚：这件事为什么现在重要？完成之后，你希望自己处于什么状态？" : "如果今天只能做一件事，它会是什么？先把这一件事放在最前面。"}</p></aside></div>;
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

function Task({ label, done = false }: { label: string; done?: boolean }) { return <div className={`task-row ${done ? "task-done" : ""}`}><span className="task-check">{done ? "✓" : ""}</span><span>{label}</span>{done ? <small>完成</small> : null}</div>; }
