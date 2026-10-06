import { useEffect, useRef, useState, type ReactNode } from "react";
import { exportEntryToVault, getVaultStatus, listEntries, saveEntry, syncEntryFromVault } from "../api/client";
import type { StructuredEntry, StructuredEntryKind, VaultStatus } from "../api/types";
import { IconBook, IconHistory } from "../components/Icons";

export type DraftOverride = Partial<{
  title: string;
  content: string;
  mood: string | null;
  metadata: Record<string, unknown>;
}>;

type DraftInitial = {
  title?: string;
  content?: string;
  mood?: string | null;
  metadata?: Record<string, unknown>;
};

type DraftOptions = {
  todayOnly?: boolean;
  limit?: number;
};

function localIsoDate(date = new Date()): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
function formatDate(value?: string | null): string {
  if (!value) return "今天";
  const date = new Date(`${value.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "short",
  }).format(date);
}

function formatUpdated(value?: string | null): string {
  if (!value) return "刚刚保存";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function excerpt(value: string): string {
  const plain = value
    .replace(/[#>*_`\[\]-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return plain ? `${plain.slice(0, 32)}${plain.length > 32 ? "…" : ""}` : "空白记录";
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) {
    if (error.message.includes("Failed to fetch")) {
      return "无法连接本地 LifeOS 后端。请确认 API 服务已启动。";
    }
    return error.message;
  }
  return "本地记录操作失败，请稍后重试。";
}

export function useEntryDraft(
  kind: StructuredEntryKind,
  initial: DraftInitial = {},
  options: DraftOptions = {},
) {
  const today = localIsoDate();
  const [id, setId] = useState<string>();
  const [entryDate, setEntryDate] = useState(today);
  const [title, setTitleState] = useState(initial.title ?? "");
  const [content, setContentState] = useState(initial.content ?? "");
  const [mood, setMoodState] = useState<string | null>(initial.mood ?? null);
  const [metadata, setMetadataState] = useState<Record<string, unknown>>(initial.metadata ?? {});
  const [history, setHistory] = useState<StructuredEntry[]>([]);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const applyEntry = (entry: StructuredEntry) => {
    setId(entry.id);
    setEntryDate(entry.entry_date || today);
    setTitleState(entry.title || "");
    setContentState(entry.content || "");
    setMoodState(entry.mood ?? null);
    setMetadataState(entry.metadata ?? {});
    setDirty(false);
  };

  const applyInitial = () => {
    setId(undefined);
    setEntryDate(today);
    setTitleState(initial.title ?? "");
    setContentState(initial.content ?? "");
    setMoodState(initial.mood ?? null);
    setMetadataState(initial.metadata ?? {});
    setDirty(false);
  };

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    listEntries(kind, { limit: options.limit ?? 80 })
      .then((entries) => {
        if (!alive) return;
        setHistory(entries);
        const entry = options.todayOnly
          ? entries.find((item) => item.entry_date === today)
          : entries[0];
        if (entry) applyEntry(entry);
        else applyInitial();
      })
      .catch((reason) => {
        if (!alive) return;
        applyInitial();
        setError(errorMessage(reason));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [kind, options.limit, options.todayOnly, today]);

  const setTitle = (value: string) => {
    setTitleState(value);
    setDirty(true);
  };

  const setContent = (value: string) => {
    setContentState(value);
    setDirty(true);
  };

  const setMood = (value: string | null) => {
    setMoodState(value);
    setDirty(true);
  };

  const setMetadata = (value: Record<string, unknown>) => {
    setMetadataState(value);
    setDirty(true);
  };

  const save = async (
    overrides: DraftOverride = {},
    mode: "version" | "update" = "version",
  ) => {
    setSaving(true);
    setError(null);
    try {
      const entry = await saveEntry({
        id: mode === "update" ? id : undefined,
        kind,
        entry_date: entryDate || today,
        title: overrides.title ?? title,
        content: overrides.content ?? content,
        mood: overrides.mood ?? mood,
        metadata: overrides.metadata ?? metadata,
      });
      applyEntry(entry);
      setHistory((current) => [entry, ...current.filter((item) => item.id !== entry.id)]);
      return entry;
    } catch (reason) {
      setError(errorMessage(reason));
      return null;
    } finally {
      setSaving(false);
    }
  };

  const replaceEntry = (entry: StructuredEntry) => {
    applyEntry(entry);
    setHistory((current) => {
      const exists = current.some((item) => item.id === entry.id);
      return exists
        ? current.map((item) => item.id === entry.id ? entry : item)
        : [entry, ...current];
    });
    setError(null);
  };

  const selectEntry = (entry: StructuredEntry) => {
    applyEntry(entry);
    setError(null);
  };

  const createNew = () => {
    applyInitial();
    setError(null);
  };

  return {
    id,
    kind,
    entryDate,
    title,
    setTitle,
    content,
    setContent,
    mood,
    setMood,
    metadata,
    setMetadata,
    history,
    saving,
    loading,
    loaded: !loading,
    dirty,
    error,
    save,
    replaceEntry,
    selectEntry,
    createNew,
  };
}

function MarkdownEditor({
  value,
  onChange,
  placeholder,
  disabled = false,
  className = "",
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  disabled?: boolean;
  className?: string;
}) {
  const editorRef = useRef<HTMLTextAreaElement>(null);

  const insert = (before: string, after = "", fallback = "") => {
    const editor = editorRef.current;
    if (!editor) return;
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    const selected = value.slice(start, end) || fallback;
    const next = `${value.slice(0, start)}${before}${selected}${after}${value.slice(end)}`;
    onChange(next);
    requestAnimationFrame(() => {
      editor.focus();
      const cursor = start + before.length + selected.length;
      editor.setSelectionRange(cursor, cursor);
    });
  };

  const tools = [
    { label: "H2", title: "插入小节标题", action: () => insert("## ", "", "小节标题") },
    { label: "待办", title: "插入任务", action: () => insert("- [ ] ", "", "下一步") },
    { label: "列表", title: "插入列表", action: () => insert("- ", "", "列表项") },
    { label: "[[ ]]", title: "插入双向链接", action: () => insert("[[", "]]", "关联笔记") },
    { label: "#", title: "插入标签", action: () => insert("#", "", "记录") },
    { label: "---", title: "插入分隔线", action: () => insert("\n---\n") },
  ];

  return (
    <div className={`markdown-editor ${className}`}>
      <div className="markdown-toolbar" aria-label="Markdown 工具">
        {tools.map((tool) => (
          <button
            type="button"
            key={tool.label}
            title={tool.title}
            onClick={tool.action}
            disabled={disabled}
          >
            {tool.label}
          </button>
        ))}
        <span>Markdown</span>
      </div>
      <textarea
        ref={editorRef}
        className="big-editor"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        disabled={disabled}
      />
    </div>
  );
}

type EntryDraft = ReturnType<typeof useEntryDraft>;

function VaultExportAction({ draft }: { draft: EntryDraft }) {
  const [status, setStatus] = useState<VaultStatus | null>(null);
  const [exporting, setExporting] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let alive = true;
    getVaultStatus()
      .then((next) => {
        if (alive) setStatus(next);
      })
      .catch(() => {
        if (alive) setStatus(null);
      });
    return () => {
      alive = false;
    };
  }, []);

  const linkedPath = typeof draft.metadata.vault_path === "string"
    ? draft.metadata.vault_path
    : "";

  const syncNow = async () => {
    if (!draft.id) {
      setMessage("请先保存当前记录");
      return;
    }
    setSyncing(true);
    setMessage("");
    try {
      const result = await syncEntryFromVault(draft.id);
      draft.replaceEntry(result.entry);
      setMessage(`已重新提取 · ${result.relative_path}`);
    } catch (reason) {
      setMessage(errorMessage(reason));
    } finally {
      setSyncing(false);
    }
  };

  const exportNow = async () => {
    setExporting(true);
    setMessage("");
    try {
      const entry = await draft.save({}, "update");
      if (!entry) {
        setMessage("请先保存当前记录");
        return;
      }
      const result = await exportEntryToVault(entry.id);
      draft.replaceEntry(result.entry);
      setMessage(`已导出 · ${result.relative_path}`);
    } catch (reason) {
      setMessage(errorMessage(reason));
    } finally {
      setExporting(false);
    }
  };

  if (!status) return <span className="vault-status muted">Vault 未连接</span>;
  if (!status.configured || !status.exists) {
    return <a className="vault-status" href="#settings">配置 Obsidian Vault</a>;
  }
  return (
    <span className="vault-export-action">
      <span className="vault-status" title={linkedPath || status.path}>
        {message || (linkedPath ? `已关联 · ${linkedPath}` : `${status.folder} · ${status.file_count} 个 Markdown`)}
      </span>
      {linkedPath ? (
        <button type="button" className="ghost compact" onClick={syncNow} disabled={syncing || exporting || draft.dirty} title={draft.dirty ? "请先保存当前修改，再重新提取 Vault 内容" : undefined}>
          {syncing ? "提取中…" : "重新提取"}
        </button>
      ) : null}
      <button type="button" className="ghost compact" onClick={exportNow} disabled={exporting || syncing}>
        {exporting ? "导出中…" : "导出到 Vault"}
      </button>
    </span>
  );
}

type WorkbenchProperty = {
  label: string;
  value: string;
};

function EntryWorkbench({
  kindLabel,
  pathLabel,
  title,
  children,
  properties,
  history,
  activeId,
  onSelectEntry,
  onNewEntry,
  canCreateNew,
  saving,
  loading,
  dirty,
  error,
  onSave,
  saveLabel,
  asideCopy,
  vaultAction,
}: {
  kindLabel: string;
  pathLabel: string;
  title: string;
  children: ReactNode;
  properties: WorkbenchProperty[];
  history: StructuredEntry[];
  activeId?: string;
  onSelectEntry: (entry: StructuredEntry) => void;
  onNewEntry?: () => void;
  canCreateNew?: boolean;
  saving: boolean;
  loading: boolean;
  dirty: boolean;
  error: string | null;
  onSave: () => void;
  saveLabel: string;
  asideCopy: string;
  vaultAction?: ReactNode;
}) {
  return (
    <div className="obsidian-workbench">
      <section className="content-card note-editor-card" aria-busy={loading}>
        <div className="note-tabbar">
          <span className="note-tab active">
            <span className="note-tab-mark"><IconBook size={12} /></span>
            <span>{title || kindLabel}</span>
            {dirty ? <i className="note-dirty-dot" aria-label="有未保存修改" /> : null}
          </span>
          <span className="note-path">{pathLabel}</span>
        </div>

        <div className="note-properties">
          {properties.map((property) => (
            <div className="note-property" key={property.label}>
              <span>{property.label}</span>
              <strong>{property.value}</strong>
            </div>
          ))}
        </div>

        {error ? <div className="entry-error" role="alert">{error}</div> : null}
        {loading ? (
          <div className="entry-loading">正在读取本地记录…</div>
        ) : (
          <div className="note-editor-body">{children}</div>
        )}

        <div className="editor-footer note-footer">
          <div className="note-footer-meta">
            <span>
              {saving
                ? "正在写入本地 SQLite…"
                : dirty
                  ? "有未保存修改"
                  : "已同步到本地 SQLite"}
            </span>
            {vaultAction}
          </div>
          <button
            className="green-button"
            onClick={onSave}
            disabled={saving || loading || (!dirty && Boolean(activeId))}
          >
            {saving ? "保存中…" : saveLabel} <span>→</span>
          </button>
        </div>
      </section>

      <aside className="content-card note-context">
        <div className="context-heading">
          <div>
            <span className="card-kicker">本地仓库</span>
            <h3>历史记录</h3>
          </div>
          <div className="context-heading-actions">
            <span className="context-count">{history.length} 条</span>
            {canCreateNew ? (
              <button
                className="text-button"
                onClick={() => {
                  if (dirty && !window.confirm("当前有未保存修改，新建记录会放弃这些修改。继续？")) return;
                  onNewEntry?.();
                }}
              >
                + 新建
              </button>
            ) : null}
          </div>
        </div>

        <div className="entry-history">
          {history.length ? history.map((entry) => (
            <button
              type="button"
              className={`history-item ${activeId === entry.id ? "active" : ""}`}
              key={entry.id}
              onClick={() => {
                if (dirty && activeId !== entry.id && !window.confirm("当前有未保存修改，打开历史记录会放弃这些修改。继续？")) return;
                onSelectEntry(entry);
              }}
              title="打开这条历史记录"
            >
              <span>{formatDate(entry.entry_date)}</span>
              <strong>{entry.title || excerpt(entry.content)}</strong>
              <small>{formatUpdated(entry.updated_at)}</small>
            </button>
          )) : (
            <div className="state-empty">还没有历史记录</div>
          )}
        </div>

        <div className="context-note">
          <span><IconHistory size={12} /> 写作提示</span>
          <p>{asideCopy}</p>
        </div>
      </aside>
    </div>
  );
}

export function PlanningPage({ phase }: { phase: boolean }) {
  const fallbackTitle = phase ? "未来 90 天规划" : "今日规划";
  const draft = useEntryDraft(
    phase ? "phase_plan" : "daily_plan",
    { title: fallbackTitle, content: "", metadata: {} },
    { todayOnly: !phase, limit: 80 },
  );
  const [intent, setIntent] = useState("");

  useEffect(() => {
    setIntent(String(draft.metadata.intent ?? ""));
  }, [draft.id, draft.metadata.intent, draft.loading]);

  const save = () => void draft.save({
    title: draft.title.trim() || fallbackTitle,
    metadata: { ...draft.metadata, intent },
  });

  return (
    <EntryWorkbench
      kindLabel={phase ? "阶段性规划" : "每日规划"}
      pathLabel={phase ? "0. 周期笔记 / 阶段规划" : `0. 周期笔记 / ${draft.entryDate}`}
      title={draft.title || fallbackTitle}
      properties={[
        { label: "类型", value: phase ? "阶段规划" : "每日规划" },
        { label: "日期", value: formatDate(draft.entryDate) },
        { label: "状态", value: draft.id ? "已创建" : "新记录" },
      ]}
      history={draft.history}
      activeId={draft.id}
      onSelectEntry={draft.selectEntry}
      onNewEntry={draft.createNew}
      canCreateNew={phase}
      saving={draft.saving}
      loading={draft.loading}
      dirty={draft.dirty}
      error={draft.error}
      onSave={save}
      saveLabel="保存规划"
      vaultAction={<VaultExportAction draft={draft} />}
      asideCopy={phase
        ? "先写清楚这个阶段想靠近的方向，再写能验证进展的结果。没有行动线索的目标，需要继续拆小。"
        : "把今天最值得推进的事情写下来。计划可以留白，但不要把重要的事交给临时状态。"}
    >
      <input
        className="note-title-input"
        value={draft.title}
        onChange={(event) => draft.setTitle(event.target.value)}
        placeholder={phase ? "给这个阶段一个名字" : "给今天一个标题"}
        disabled={draft.loading}
      />
      <label className="note-field">
        <span>{phase ? "阶段命题" : "今日意图"}</span>
        <input
          value={intent}
          onChange={(event) => setIntent(event.target.value)}
          placeholder={phase ? "例如：建立稳定的创作节奏" : "例如：完成最重要的一件事"}
          disabled={draft.loading}
        />
      </label>
      <MarkdownEditor
        value={draft.content}
        onChange={draft.setContent}
        placeholder={phase
          ? "写下阶段目标、关键结果和下一步行动。"
          : "写下今天的重点、时间块和需要留意的边界。"}
        disabled={draft.loading}
      />
    </EntryWorkbench>
  );
}

const DAILY_REVIEW_QUESTIONS = [
  "今天最有能量的时刻是什么？",
  "有什么事情没有完成？真正的原因是什么？",
  "明天醒来后，你最想先做什么？",
];

const PHASE_REVIEW_QUESTIONS = [
  "这段时间，什么真正带来了进展？",
  "什么消耗了你，却没有带来相应的回报？",
  "下一阶段，你要继续、停止或开始什么？",
];

export function ReviewPage({ phase }: { phase: boolean }) {
  const questions = phase ? PHASE_REVIEW_QUESTIONS : DAILY_REVIEW_QUESTIONS;
  const fallbackTitle = phase ? "阶段性复盘" : "每日复盘";
  const draft = useEntryDraft(
    phase ? "phase_review" : "daily_review",
    { title: fallbackTitle, content: "", metadata: {} },
    { todayOnly: !phase, limit: 80 },
  );
  const [answers, setAnswers] = useState<string[]>(() => questions.map(() => ""));
  useEffect(() => {
    const savedAnswers = draft.metadata.answers;
    setAnswers(
      Array.isArray(savedAnswers)
        ? questions.map((_, index) => String(savedAnswers[index] ?? ""))
        : questions.map(() => ""),
    );
  }, [draft.id, draft.metadata.answers, phase]);

  const save = () => {
    const content = questions
      .map((question, index) => `## ${question}\n\n${answers[index] || "_未填写_"}`)
      .join("\n\n");
    void draft.save({
      title: draft.title.trim() || fallbackTitle,
      content,
      metadata: { ...draft.metadata, answers },
    });
  };

  return (
    <EntryWorkbench
      kindLabel={phase ? "阶段性复盘" : "每日复盘"}
      pathLabel={phase ? "0. 周期笔记 / 阶段复盘" : `0. 周期笔记 / ${draft.entryDate}`}
      title={draft.title || fallbackTitle}
      properties={[
        { label: "类型", value: phase ? "阶段复盘" : "每日复盘" },
        { label: "日期", value: formatDate(draft.entryDate) },
      ]}
      history={draft.history}
      activeId={draft.id}
      onSelectEntry={draft.selectEntry}
      onNewEntry={draft.createNew}
      canCreateNew={phase}
      saving={draft.saving}
      loading={draft.loading}
      dirty={draft.dirty}
      error={draft.error}
      onSave={save}
      saveLabel="完成复盘"
      vaultAction={<VaultExportAction draft={draft} />}
      asideCopy="复盘不是给自己打分，而是把经验变成下一次可用的判断。写事实，也写事实带来的变化。"
    >
      <input
        className="note-title-input"
        value={draft.title}
        onChange={(event) => draft.setTitle(event.target.value)}
        placeholder={phase ? "给这段复盘一个标题" : "给今天的复盘一个标题"}
        disabled={draft.loading}
      />
      {questions.map((question, index) => (
        <label className="prompt-block" key={question}>
          <span>{question}</span>
          <textarea
            placeholder="写下你的想法…"
            value={answers[index]}
            onChange={(event) => setAnswers((current) => current.map((value, position) => (
              position === index ? event.target.value : value
            )))}
            disabled={draft.loading}
          />
        </label>
      ))}
    </EntryWorkbench>
  );
}

export function DiaryPage() {
  const moods = ["☀ 平静", "☁ 有点累", "✦ 充满能量", "♡ 说不清"];
  const draft = useEntryDraft(
    "diary",
    { title: `日记 · ${formatDate(localIsoDate())}`, content: "", metadata: { tags: [] } },
    { todayOnly: true, limit: 80 },
  );
  const [tags, setTags] = useState("");

  useEffect(() => {
    const savedTags = draft.metadata.tags;
    setTags(Array.isArray(savedTags) ? savedTags.map((tag) => `#${String(tag).replace(/^#/, "")}`).join(" ") : "");
  }, [draft.id, draft.metadata.tags]);

  const save = () => void draft.save({
    title: draft.title.trim() || `日记 · ${formatDate(draft.entryDate)}`,
    metadata: {
      ...draft.metadata,
      tags: tags.split(/\s+/).map((tag) => tag.replace(/^#/, "")).filter(Boolean),
    },
  });

  return (
    <EntryWorkbench
      kindLabel="日记"
      pathLabel={`0. 周期笔记 / Diary / ${draft.entryDate}`}
      title={draft.title || `日记 · ${formatDate(draft.entryDate)}`}
      properties={[
        { label: "类型", value: "日记" },
        { label: "日期", value: formatDate(draft.entryDate) },
        { label: "心情", value: draft.mood || "未选择" },
      ]}
      history={draft.history}
      activeId={draft.id}
      onSelectEntry={draft.selectEntry}
      canCreateNew={false}
      saving={draft.saving}
      loading={draft.loading}
      dirty={draft.dirty}
      error={draft.error}
      onSave={save}
      saveLabel="保存日记"
      vaultAction={<VaultExportAction draft={draft} />}
      asideCopy="日记优先保留真实经验，不急着总结。以后回看时，具体的场景会比抽象评价更有价值。"
    >
      <input
        className="note-title-input"
        value={draft.title}
        onChange={(event) => draft.setTitle(event.target.value)}
        placeholder="给今天留一个标题"
        disabled={draft.loading}
      />
      <div className="diary-mood">
        <span>今天的心情</span>
        {moods.map((mood) => (
          <button
            className={draft.mood === mood ? "selected" : ""}
            key={mood}
            onClick={() => draft.setMood(mood)}
            disabled={draft.loading}
          >
            {mood}
          </button>
        ))}
      </div>
      <label className="note-field compact">
        <span>标签</span>
        <input
          value={tags}
          onChange={(event) => setTags(event.target.value)}
          placeholder="#工作 #生活 #复盘"
          disabled={draft.loading}
        />
      </label>
      <MarkdownEditor
        value={draft.content}
        onChange={draft.setContent}
        placeholder="今天有什么值得被写下来？"
        disabled={draft.loading}
      />
      <div className="writing-count">{draft.content.trim().length} 字</div>
    </EntryWorkbench>
  );
}

export function InsightPage() {
  const draft = useEntryDraft("insight", { title: "", content: "", metadata: { tags: [] } }, { limit: 80 });
  const [tags, setTags] = useState("");

  useEffect(() => {
    const savedTags = draft.metadata.tags;
    setTags(Array.isArray(savedTags) ? savedTags.map((tag) => `#${String(tag).replace(/^#/, "")}`).join(" ") : "");
  }, [draft.id, draft.metadata.tags]);

  const save = () => void draft.save({
    title: draft.title.trim() || "未命名心得",
    metadata: {
      ...draft.metadata,
      tags: tags.split(/\s+/).map((tag) => tag.replace(/^#/, "")).filter(Boolean),
    },
  });

  return (
    <EntryWorkbench
      kindLabel="心得 / 体验"
      pathLabel="3. 资源 / Insights"
      title={draft.title || "未命名心得"}
      properties={[
        { label: "类型", value: "心得 / 体验" },
        { label: "日期", value: formatDate(draft.entryDate) },
        { label: "标签", value: tags || "未添加" },
      ]}
      history={draft.history}
      activeId={draft.id}
      onSelectEntry={draft.selectEntry}
      onNewEntry={draft.createNew}
      canCreateNew
      saving={draft.saving}
      loading={draft.loading}
      dirty={draft.dirty}
      error={draft.error}
      onSave={save}
      saveLabel="保存心得"
      vaultAction={<VaultExportAction draft={draft} />}
      asideCopy="把体验写成可以再次使用的材料：发生了什么、它改变了什么、以后遇到类似情境时你会怎么做。"
    >
      <input
        className="note-title-input"
        value={draft.title}
        onChange={(event) => draft.setTitle(event.target.value)}
        placeholder="先写一个标题…"
        disabled={draft.loading}
      />
      <label className="note-field compact">
        <span>标签</span>
        <input
          value={tags}
          onChange={(event) => setTags(event.target.value)}
          placeholder="#阅读 #项目 #方法"
          disabled={draft.loading}
        />
      </label>
      <MarkdownEditor
        value={draft.content}
        onChange={draft.setContent}
        placeholder="一段阅读后的感受、一次旅途中的发现，或者一个你不想忘记的瞬间…"
        disabled={draft.loading}
      />
      <div className="writing-count">{draft.content.trim().length} 字</div>
    </EntryWorkbench>
  );
}

export function FeedbackPage() {
  const categories = ["功能建议", "使用感受", "发现问题", "其他"];
  const draft = useEntryDraft(
    "feedback",
    { title: "使用反馈", content: "", metadata: { category: "使用感受" } },
    { limit: 80 },
  );
  const [category, setCategory] = useState("使用感受");

  useEffect(() => {
    setCategory(String(draft.metadata.category || "使用感受"));
  }, [draft.id, draft.metadata.category]);

  const save = () => void draft.save({
    title: draft.title.trim() || "使用反馈",
    metadata: { ...draft.metadata, category },
  });

  return (
    <EntryWorkbench
      kindLabel="反馈"
      pathLabel="系统 / 反馈"
      title={draft.title || "使用反馈"}
      properties={[
        { label: "类型", value: "使用反馈" },
        { label: "分类", value: category },
        { label: "日期", value: formatDate(draft.entryDate) },
      ]}
      history={draft.history}
      activeId={draft.id}
      onSelectEntry={draft.selectEntry}
      onNewEntry={draft.createNew}
      canCreateNew
      saving={draft.saving}
      loading={draft.loading}
      dirty={draft.dirty}
      error={draft.error}
      onSave={save}
      saveLabel="提交反馈"
      asideCopy="反馈会按每次提交保存为独立版本。历史记录可以重新打开，不需要覆盖之前写过的内容。"
    >
      <input
        className="note-title-input"
        value={draft.title}
        onChange={(event) => draft.setTitle(event.target.value)}
        placeholder="给这条反馈一个标题"
        disabled={draft.loading}
      />
      <div className="feedback-tags">
        {categories.map((item) => (
          <button
            type="button"
            className={category === item ? "selected" : ""}
            key={item}
            onClick={() => setCategory(item)}
            disabled={draft.loading}
          >
            {item}
          </button>
        ))}
      </div>
      <MarkdownEditor
        value={draft.content}
        onChange={draft.setContent}
        placeholder="哪里让你觉得顺手？哪里还不够像你？"
        disabled={draft.loading}
      />
    </EntryWorkbench>
  );
}
