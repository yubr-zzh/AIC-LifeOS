/**
 * 工具调用的一行摘要。
 *
 * 纪律：参数来自 Agent，属于**不可信内容**。这里只做「取字段 + 截断 + 拼固定
 * 动词」，不做任何改写或推断。拼进摘要的文本会渲染成看起来像系统的文字，
 * 是整套 UI 里最容易被伪造的地方。
 */

const MAX = 60;

function clip(s: string, n = MAX): string {
  const t = s.replace(/\s+/g, " ").trim();
  return t.length > n ? `${t.slice(0, n)}…` : t;
}

/** 同时处理 `/` 与 `\`：项目在 Windows 上跑，路径两种分隔符都会出现。 */
export function basename(p: unknown): string {
  if (typeof p !== "string") return "";
  const parts = p.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? p;
}

function str(input: unknown, key: string): string {
  if (!input || typeof input !== "object") return "";
  const v = (input as Record<string, unknown>)[key];
  return typeof v === "string" ? v : "";
}

/**
 * 从工具名 + 输入生成一行摘要。
 * 只认识最常见的几种，其余统一降级为工具名本身。
 */
export function zhaiYao(name: string, input: unknown): string {
  switch (name) {
    case "Read": {
      const f = basename(str(input, "file_path"));
      return f ? `读取 ${f}` : "读取文件";
    }
    case "Write": {
      const f = basename(str(input, "file_path"));
      return f ? `写入 ${f}` : "写入文件";
    }
    case "Edit":
    case "MultiEdit":
    case "NotebookEdit": {
      const f = basename(str(input, "file_path") || str(input, "notebook_path"));
      return f ? `修改 ${f}` : "修改文件";
    }
    case "Bash": {
      const c = str(input, "command");
      return c ? `运行 ${clip(c)}` : "运行命令";
    }
    case "BashOutput":
      return "读取命令输出";
    case "Glob": {
      const p = str(input, "pattern");
      return p ? `匹配 ${clip(p, 40)}` : "匹配文件";
    }
    case "Grep": {
      const p = str(input, "pattern");
      return p ? `搜索 ${clip(p, 40)}` : "搜索内容";
    }
    case "WebFetch": {
      const u = str(input, "url");
      return u ? `访问 ${clip(u, 48)}` : "访问网页";
    }
    case "WebSearch": {
      const q = str(input, "query");
      return q ? `搜索 ${clip(q, 40)}` : "联网搜索";
    }
    case "TodoWrite":
      return "更新任务清单";
    case "AskUserQuestion":
      return "向你提问";
    case "Task":
    case "Agent": {
      const d = str(input, "description");
      return d ? `委派 ${clip(d, 40)}` : "委派子任务";
    }
    default:
      return name || "工具调用";
  }
}

/**
 * 合并多个连续调用时的组摘要。
 *
 * **只接收工具名计数，不接收参数**——理由同 `zhaiYao`。
 */
export function groupLabel(names: string[], n: number): string {
  const count = n || names.length;
  if (count <= 1) return names[0] ? zhaiYao(names[0], null) : "工具调用";
  const all = (pred: (s: string) => boolean) => names.length > 0 && names.every(pred);
  if (all((s) => s === "Read")) return `读取了 ${count} 个文件`;
  if (all((s) => s === "Grep" || s === "Glob")) return `搜索了 ${count} 次`;
  if (all((s) => s === "Edit" || s === "Write" || s === "MultiEdit")) return `修改了 ${count} 个文件`;
  if (all((s) => s === "Bash")) return `运行了 ${count} 条命令`;
  return `执行了 ${count} 个工具`;
}
