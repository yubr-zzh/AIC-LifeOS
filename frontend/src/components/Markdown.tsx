import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeHighlight from "rehype-highlight";

/**
 * Agent / LifeOS 正文的 Markdown 渲染。
 *
 * 安全边界：**不挂 rehype-raw**。Agent 输出是不可信内容，原文里的 HTML
 * 一律按字面文本渲染，不走 innerHTML，也就没有注入面。
 *
 * 工具产出（ToolStep 的结果区）**不走这里**，仍是 `<pre>`：那是原始
 * 字节，不该被当成文档解释。
 */
const components: Components = {
  a: ({ node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
  img: ({ node, ...props }) => (
    // 不自动加载第三方图：加 lazy + no-referrer，避免 Agent 输出变成信标。
    <img {...props} alt={props.alt ?? ""} loading="lazy" referrerPolicy="no-referrer" />
  ),
  // 窄侧栏放不下宽表：包一层横向滚动容器，别让整列被撑破。
  table: ({ children }) => (
    <div className="md-table">
      <table>{children}</table>
    </div>
  ),
};

const remarkPlugins = [remarkGfm, remarkMath];
const rehypePlugins: Parameters<typeof ReactMarkdown>[0]["rehypePlugins"] = [
  rehypeKatex,
  [rehypeHighlight, { detect: true, ignoreMissing: true }],
];

export function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={rehypePlugins}
        components={components}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
