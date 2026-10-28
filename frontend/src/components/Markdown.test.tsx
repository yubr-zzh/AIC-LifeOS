import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { Markdown } from "./Markdown";

const html = (text: string) => {
  const { container } = render(<Markdown text={text} />);
  return container.querySelector(".md") as HTMLElement;
};

describe("Markdown", () => {
  it("渲染加粗、行内代码与列表", () => {
    const root = html("**重点** 和 `npm test`\n\n- 一\n- 二");
    expect(root.querySelector("strong")?.textContent).toBe("重点");
    expect(root.querySelector("p code")?.textContent).toBe("npm test");
    expect(root.querySelectorAll("li")).toHaveLength(2);
  });

  it("代码块带语言时会被高亮，且保留原文", () => {
    const root = html("```ts\nconst a = 1;\n```");
    const code = root.querySelector("pre code");
    expect(code?.textContent).toContain("const a = 1;");
    expect(code?.className).toContain("hljs");
    expect(root.querySelector(".hljs-keyword")?.textContent).toBe("const");
  });

  it("GFM 表格渲染成 table，并包在可横滚的容器里", () => {
    const root = html("| a | b |\n| - | - |\n| 1 | 2 |");
    expect(root.querySelector(".md-table table")).toBeTruthy();
    expect(root.querySelectorAll("th")).toHaveLength(2);
    expect(root.querySelector("td")?.textContent).toBe("1");
  });

  it("行内与块级公式都由 KaTeX 渲染成 DOM，而不是留 $ 原文", () => {
    const root = html("质量 $E=mc^2$ 与\n\n$$\n\\int_0^1 x\\,dx\n$$");
    expect(root.querySelectorAll(".katex").length).toBeGreaterThanOrEqual(2);
    expect(root.querySelector(".katex-display")).toBeTruthy();
    expect(root.textContent).not.toContain("$$");
  });

  it("不可信 HTML 不注入：标签被当字面文本，不会变成元素", () => {
    const root = html('<script>alert(1)</script>\n\n<img src=x onerror="alert(2)">');
    expect(root.querySelector("script")).toBeNull();
    expect(root.querySelector("img")).toBeNull();
    expect(root.querySelector("[onerror]")).toBeNull();
    // 原文以转义文本呈现，说明走的是文本节点而不是 innerHTML
    expect(root.textContent).toContain("<script>alert(1)</script>");
  });

  it("链接一律新窗口打开并切断 opener", () => {
    const root = html("[文档](https://example.com/a)");
    const a = root.querySelector("a") as HTMLAnchorElement;
    expect(a.getAttribute("href")).toBe("https://example.com/a");
    expect(a.getAttribute("target")).toBe("_blank");
    expect(a.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("流式过程中的半截语法不会抛错", () => {
    expect(() => html("上面写了一半的 **加粗")).not.toThrow();
    expect(() => html("```ts\nconst a = ")).not.toThrow();
  });
});
