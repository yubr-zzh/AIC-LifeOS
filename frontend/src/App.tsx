import { useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "./state/store";
import { useAgentStore } from "./state/agentStore";
import { useAgentStream } from "./hooks/useAgentStream";
import { listEntries, proposeEntryMemoryCandidate, saveEntry } from "./api/client";
import type { MemoryScope, StructuredEntryKind } from "./api/types";
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
import { IconBook, IconBolt, IconCalendar, IconHome, IconMessage, IconSettings, IconSpark, IconSun } from "./components/Icons";

type SectionId =
  | "home"
  | "daily-plan"
  | "daily-review"
  | "phase-plan"
  | "phase-review"
  | "chat"
  | "agents"
  | "feedback"
  | "diary"
  | "insight"
  | "admin";

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
  agents: { eyebrow: "连接 · 本地 Agent", title: "把执行交给你机器上的 Agent", description: "LifeOS 负责规划与拆解，本机 Agent 负责动手。审批始终由你点。" },
  feedback: { eyebrow: "系统 · 反馈", title: "让 LifeOS 越来越懂你", description: "告诉我们哪里顺手，哪里还可以更贴近你的工作方式。" },
  diary: { eyebrow: "记录 · 日记", title: "给今天留一页空白", description: "不必写得完整，想到什么就从哪里开始。" },
  insight: { eyebrow: "沉淀 · 心得 / 体验", title: "把经历变成自己的东西", description: "记录一个念头、一种感受，或者一次值得记住的体验。" },
  admin: { eyebrow: "后台 · 系统", title: "LifeOS 的运行后台", description: "这里放置事件、记忆、技能与运行状态等工程信息。" },
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
      </aside>

      <div className="content-shell">
        <header className="workspace-header">
          <div className="breadcrumb"><span>LifeOS</span><i>/</i><strong>{meta.eyebrow.split(" · ")[0]}</strong></div>
          <div className="header-actions">
            <span className="sync-label"><span className="status-orb" />刚刚同步</span>
            <button className="header-icon-button" onClick={() => setDark(!dark)} title="切换主题" aria-label={`切换到${dark ? "浅色" : "夜间"}主题`} aria-pressed={dark}>{dark ? <IconSun size={16} /> : <IconSpark size={16} />}</button>
            <button className="header-icon-button" onClick={() => setSettingsOpen(!settingsOpen)} title="设置" aria-label="设置" aria-expanded={settingsOpen}><IconSettings size={16} /></button>
            <div className="avatar">Z</div>
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
          <SectionContent active={active} store={store} agent={agent} api={api} onNavigate={select} />
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
}: {
  active: SectionId;
  store: ReturnType<typeof useStore>;
  agent: ReturnType<typeof useAgentStore>;
  api: ReturnType<typeof useAgentStream>;
  onNavigate: (id: SectionId) => void;
}) {
  if (active === "chat") {
    // 对话保持内容优先；运行指标留在系统后台，执行面板按需展开。
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
          <div className="chat-split-grid">
            {zuo}
            <AgentPanel store={agent} api={api}
              onCandidateCreated={() => void store.refreshAll()}
              onCollapse={() => agent.setLayout("collapsed")} />
          </div>
        ) : (
          zuo
        )}
      </>
    );
  }
  if (active === "agents") return <AgentsSection store={agent} api={api} onGoChat={() => onNavigate("chat")} />;
  if (active === "feedback") return <FeedbackPage />;
  if (active === "diary") return <DiaryPage />;
  if (active === "insight") return <InsightPage />;
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

function FeedbackPage() { const draft = useEntryDraft("feedback", {}); const [category, setCategory] = useState("使用感受"); return <div className="feedback-layout"><section className="content-card feedback-main"><span className="card-kicker">写给 LifeOS</span><h2>哪里让你觉得顺手？哪里还不够像你？</h2><textarea className="feedback-editor" placeholder="可以是一句话，也可以是一段具体的经历…" value={draft.content} onChange={(event) => draft.setContent(event.target.value)} /><div className="feedback-tags">{["功能建议", "使用感受", "发现问题", "其他"].map((tag) => <button className={category === tag ? "selected" : ""} key={tag} onClick={() => setCategory(tag)}>{tag}</button>)}</div><button className="green-button" onClick={() => void draft.save({ metadata: { category } })} disabled={draft.saving}>{draft.saving ? "提交中…" : "提交反馈"} <span>→</span></button></section><section className="content-card feedback-history"><div className="card-heading"><div><span className="card-kicker">你的声音</span><h2>最近反馈</h2></div><span className="soft-count">来自 SQLite</span></div>{draft.content ? <div className="feedback-note"><span>✓</span><div><strong>{draft.content.slice(0, 24)}{draft.content.length > 24 ? "…" : ""}</strong><small>刚刚 · 已保存</small></div></div> : <div className="state-empty">还没有新的反馈</div>}</section></div>; }

function DiaryPage() { const draft = useEntryDraft("diary", {}); const moods = ["☀ 平静", "☁ 有点累", "✦ 充满能量", "♡ 说不清"]; return <div className="diary-layout"><section className="content-card diary-editor"><div className="card-heading"><div><span className="card-kicker">今天 · 私人记录</span><h2>今天的日记</h2></div><span className="soft-count">{draft.id ? "已保存" : "新记录"}</span></div><textarea className="big-editor diary-text" placeholder="今天有什么值得被写下来？" value={draft.content} onChange={(event) => draft.setContent(event.target.value)} /><div className="diary-mood"><span>今天的心情</span>{moods.map((mood) => <button className={draft.mood === mood ? "selected" : ""} key={mood} onClick={() => draft.setMood(mood)}>{mood}</button>)}</div><div className="editor-footer"><span>内容会保存到本地 SQLite</span><button className="green-button" onClick={() => void draft.save()} disabled={draft.saving}>{draft.saving ? "保存中…" : "保存日记"} <span>→</span></button></div></section><aside className="content-card diary-aside"><span className="card-kicker">近日日记</span><h3>那些被你留住的时刻</h3><div className="diary-history"><div><strong>本地存储</strong><span>你的日记会按日期保存在 LifeOS SQLite 数据库中。</span></div><div><strong>私人空间</strong><span>这些内容不会进入 Git，也不会写入事件队列。</span></div></div></aside></div>; }

function InsightPage() { const draft = useEntryDraft("insight", {}); return <div className="insight-layout"><section className="content-card insight-editor"><div className="card-heading"><div><span className="card-kicker">心得 / 体验</span><h2>记录一个正在发酵的想法</h2></div><span className="soft-count">{draft.id ? "已保存" : "新记录"}</span></div><input className="insight-title" placeholder="先写一个标题…" value={draft.title} onChange={(event) => draft.setTitle(event.target.value)} /><textarea className="big-editor insight-text" placeholder="一段阅读后的感受、一次旅途中的发现，或者一个你不想忘记的瞬间…" value={draft.content} onChange={(event) => draft.setContent(event.target.value)} /><div className="editor-footer"><span>内容会保存到本地 SQLite</span><button className="green-button" onClick={() => void draft.save()} disabled={draft.saving}>{draft.saving ? "保存中…" : "保存心得"} <span>→</span></button></div></section><aside className="content-card insight-aside"><span className="card-kicker">你的知识花园</span><h3>心得会在时间里长出新的连接。</h3><p>把体验留下来，未来的你会更容易看见自己走过的路。</p><div className="insight-count"><strong>SQLite</strong><span>结构化保存</span></div></aside></div>; }

function AdminPage({ store }: { store: ReturnType<typeof useStore> }) { return <div className="admin-page"><div className="admin-banner"><div><span className="card-kicker">系统后台</span><h2>工程信息集中在这里</h2><p>普通使用页面保持安静。只有进入后台，才会看到 Agent、事件、记忆和 Trace 等运行细节。</p></div><span className="admin-badge">开发者视图</span></div><div className="admin-flow"><DataFlowView store={store} /></div><div className="admin-grid"><RuntimeRail store={store} /><EventsPanel store={store} /><MemoryPanel store={store} /><SkillsPanel store={store} /><PermissionsPanel store={store} /><TracePanel store={store} /></div></div>; }

function Task({ label, done = false }: { label: string; done?: boolean }) { return <div className={`task-row ${done ? "task-done" : ""}`}><span className="task-check">{done ? "✓" : ""}</span><span>{label}</span>{done ? <small>完成</small> : null}</div>; }
