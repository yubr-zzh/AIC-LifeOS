// Lightweight Markdown editor inspired by mdx-editor/editor, uiwjs/react-md-editor
// and outline/rich-markdown-editor; no extra runtime dependency is required.
import React, { useMemo, useRef, useState } from "react";

interface Props {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  ariaLabel?: string;
  className?: string;
  minHeight?: number;
}

function inlineNodes(text: string): React.ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|_[^_]+_|\[[^\]]+\]\([^)]+\))/g);
  return parts.filter(Boolean).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    if (part.startsWith("_") && part.endsWith("_")) {
      return <em key={index}>{part.slice(1, -1)}</em>;
    }
    const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
    if (link) {
      const href = /^(https?:\/\/|mailto:)/i.test(link[2]) ? link[2] : "#";
      return <a key={index} href={href} target="_blank" rel="noreferrer">{link[1]}</a>;
    }
    return <React.Fragment key={index}>{part}</React.Fragment>;
  });
}

function MarkdownPreview({ value }: { value: string }) {
  const blocks = useMemo(() => {
    const lines = value.split("\n");
    const result: React.ReactNode[] = [];
    let list: { type: "ul" | "ol"; items: string[] } | null = null;
    let code: string[] | null = null;

    const flushList = () => {
      if (!list) return;
      const items = list.items.map((item, index) => {
        const task = /^\[([ xX])\]\s+/.exec(item);
        return <li key={index} className={task ? "markdown-task" : undefined}>{task ? <><input type="checkbox" checked={task[1].toLowerCase() === "x"} readOnly />{inlineNodes(item.slice(task[0].length))}</> : inlineNodes(item)}</li>;
      });
      result.push(list.type === "ul" ? <ul key={`list-${result.length}`}>{items}</ul> : <ol key={`list-${result.length}`}>{items}</ol>);
      list = null;
    };

    for (const line of lines) {
      if (line.trim().startsWith("```")) {
        flushList();
        if (code) {
          result.push(<pre key={`code-${result.length}`}><code>{code.join("\n")}</code></pre>);
          code = null;
        } else {
          code = [];
        }
        continue;
      }
      if (code) { code.push(line); continue; }
      const heading = /^(#{1,3})\s+(.+)$/.exec(line);
      if (heading) {
        flushList();
        const level = heading[1].length;
        if (level === 1) result.push(<h1 key={`h-${result.length}`}>{inlineNodes(heading[2])}</h1>);
        else if (level === 2) result.push(<h2 key={`h-${result.length}`}>{inlineNodes(heading[2])}</h2>);
        else result.push(<h3 key={`h-${result.length}`}>{inlineNodes(heading[2])}</h3>);
        continue;
      }
      if (/^\s*[-*]\s+/.test(line)) {
        if (list?.type !== "ul") { flushList(); list = { type: "ul", items: [] }; }
        list.items.push(line.replace(/^\s*[-*]\s+/, ""));
        continue;
      }
      if (/^\s*\d+\.\s+/.test(line)) {
        if (list?.type !== "ol") { flushList(); list = { type: "ol", items: [] }; }
        list.items.push(line.replace(/^\s*\d+\.\s+/, ""));
        continue;
      }
      if (/^>\s?/.test(line)) {
        flushList();
        result.push(<blockquote key={`q-${result.length}`}>{inlineNodes(line.replace(/^>\s?/, ""))}</blockquote>);
        continue;
      }
      if (!line.trim()) { flushList(); continue; }
      flushList();
      result.push(<p key={`p-${result.length}`}>{inlineNodes(line)}</p>);
    }
    flushList();
    if (code) result.push(<pre key={`code-${result.length}`}><code>{code.join("\n")}</code></pre>);
    return result;
  }, [value]);

  if (!value.trim()) return <p className="markdown-preview-empty">还没有内容。切回编辑开始书写。</p>;
  return <div className="markdown-preview">{blocks}</div>;
}

export function MarkdownEditor({ value, onChange, placeholder, ariaLabel, className, minHeight = 280 }: Props) {
  const area = useRef<HTMLTextAreaElement>(null);
  const [preview, setPreview] = useState(false);
  const [slashQuery, setSlashQuery] = useState<string | null>(null);
  const [hasSelection, setHasSelection] = useState(false);

  const surround = (before: string, after: string, fallback: string) => {
    const element = area.current;
    if (!element) {
      onChange(`${value}${before}${fallback}${after}`);
      return;
    }
    const start = element.selectionStart;
    const end = element.selectionEnd;
    const selected = value.slice(start, end) || fallback;
    const next = `${value.slice(0, start)}${before}${selected}${after}${value.slice(end)}`;
    onChange(next);
    requestAnimationFrame(() => {
      element.focus();
      element.setSelectionRange(start + before.length, start + before.length + selected.length);
    });
  };

  const prefixLine = (prefix: string) => {
    const element = area.current;
    if (!element) return;
    const start = element.selectionStart;
    const lineStart = value.lastIndexOf("\n", start - 1) + 1;
    const next = `${value.slice(0, lineStart)}${prefix}${value.slice(lineStart)}`;
    onChange(next);
    requestAnimationFrame(() => {
      element.focus();
      element.setSelectionRange(start + prefix.length, start + prefix.length);
    });
  };

  const applySlash = (command: string) => {
    const element = area.current;
    if (!element) return;
    const cursor = element.selectionStart;
    const lineStart = value.lastIndexOf("\n", cursor - 1) + 1;
    const before = value.slice(lineStart, cursor);
    const match = /^\/([^\s]*)$/.exec(before);
    if (!match) return;
    const replacement = command === "task" ? "- [ ] " : command === "bullet" ? "- " : command === "number" ? "1. " : command === "quote" ? "> " : "## ";
    const next = `${value.slice(0, lineStart)}${replacement}${value.slice(cursor)}`;
    onChange(next);
    setSlashQuery(null);
    requestAnimationFrame(() => {
      element.focus();
      element.setSelectionRange(lineStart + replacement.length, lineStart + replacement.length);
    });
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const element = area.current;
    if (!element) return;
    const cursor = element.selectionStart;
    const lineStart = value.lastIndexOf("\n", cursor - 1) + 1;
    const line = value.slice(lineStart, cursor);
    if (event.key === "Escape" && slashQuery !== null) {
      event.preventDefault();
      setSlashQuery(null);
      return;
    }
    if (event.key === "Enter" && slashQuery !== null) {
      event.preventDefault();
      applySlash(slashQuery || "task");
      return;
    }
    if (event.key === "Enter") {
      const list = /^(\s*)([-*]|\d+\.)\s+(.*)$/.exec(line);
      if (list && !list[3].trim()) {
        event.preventDefault();
        onChange(`${value.slice(0, lineStart)}${value.slice(cursor)}`);
        return;
      }
      if (list) {
        event.preventDefault();
        const marker = /^\d+\./.test(list[2]) ? `${Number.parseInt(list[2], 10) + 1}. ` : `${list[2]} `;
        onChange(`${value.slice(0, cursor)}\n${list[1]}${marker}${value.slice(cursor)}`);
        requestAnimationFrame(() => element.setSelectionRange(cursor + marker.length + 1, cursor + marker.length + 1));
        return;
      }
    }
    const slash = /^\/([^\s]*)$/.exec(line);
    if (slash) setSlashQuery(slash[1]);
    else if (slashQuery !== null) setSlashQuery(null);
  };

  const tools = [
    { label: "H2", title: "二级标题", action: () => prefixLine("## ") },
    { label: "B", title: "粗体", action: () => surround("**", "**", "粗体文本") },
    { label: "I", title: "斜体", action: () => surround("_", "_", "斜体文本") },
    { label: "•", title: "无序列表", action: () => prefixLine("- ") },
    { label: "1.", title: "有序列表", action: () => prefixLine("1. ") },
    { label: "❝", title: "引用", action: () => prefixLine("> ") },
    { label: "<>", title: "行内代码", action: () => surround("`", "`", "代码") },
    { label: "↗", title: "链接", action: () => surround("[", "](https://)", "链接文字") },
  ];

  return (
    <div className={`markdown-editor ${className ?? ""}`}>
      <div className="markdown-toolbar" role="toolbar" aria-label="文本格式工具">
        <div className="markdown-tools">
          {tools.map((tool) => (
            <button key={tool.title} type="button" title={tool.title} aria-label={tool.title}
              onMouseDown={(event) => event.preventDefault()} onClick={tool.action} disabled={preview}>
              {tool.label}
            </button>
          ))}
        </div>
        <button type="button" className={`markdown-mode ${preview ? "active" : ""}`} onClick={() => setPreview((current) => !current)} aria-pressed={preview}>
          {preview ? "编辑" : "预览"}
        </button>
      </div>
      {preview ? <MarkdownPreview value={value} /> : (
        <textarea ref={area} className="markdown-input" value={value} onChange={(event) => {
          const next = event.target.value;
          onChange(next);
          const cursor = event.target.selectionStart;
          const lineStart = next.lastIndexOf("\n", cursor - 1) + 1;
          const line = next.slice(lineStart, cursor);
          const slash = /^\/([^\s]*)$/.exec(line);
          setSlashQuery(slash ? slash[1] : null);
        }}
          onKeyDown={handleKeyDown}
          onSelect={(event) => setHasSelection(event.currentTarget.selectionStart !== event.currentTarget.selectionEnd)}
          placeholder={placeholder} aria-label={ariaLabel ?? "Markdown 编辑器"} style={{ minHeight }} />
      )}
      {!preview && hasSelection ? <div className="markdown-selection-tools" role="toolbar" aria-label="选中文本格式">
        <button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => surround("**", "**", "粗体文本")}><strong>B</strong></button>
        <button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => surround("_", "_", "斜体文本")}><em>I</em></button>
        <button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => surround("`", "`", "代码")}>Code</button>
      </div> : null}
      {!preview && slashQuery !== null ? (
        <div className="markdown-slash-menu" role="listbox" aria-label="格式命令">
          {[['task', '任务清单', '待办事项'], ['bullet', '无序列表', '- item'], ['number', '有序列表', '1. item'], ['heading', '标题', '## 标题'], ['quote', '引用', '> 引用']]
            .filter(([, label]) => !slashQuery || label.includes(slashQuery))
            .map(([command, label, hint]) => <button type="button" key={command} onMouseDown={(event) => event.preventDefault()} onClick={() => applySlash(command)}><strong>{label}</strong><span>{hint}</span></button>)}
        </div>
      ) : null}
      <div className="markdown-status">
        <span>支持 Markdown · 标题、列表、引用与代码块</span>
        <span>{value.length} 字符</span>
      </div>
    </div>
  );
}
