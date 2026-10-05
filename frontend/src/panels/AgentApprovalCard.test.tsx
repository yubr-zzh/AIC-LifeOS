import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { AgentApprovalCard } from "./AgentApprovalCard";
import type { PermissionRequest } from "../api/agentTypes";

const shen = (a: Partial<PermissionRequest> = {}): PermissionRequest => ({
  requestId: "r-1", sessionId: "s-1", toolName: "Bash", toolInput: { command: "pytest -q" },
  title: "跑测试", displayName: "Bash", description: "", blockedPath: null, decisionReason: null,
  agentId: "claude-code", suggestions: [], inputTruncated: false, originalByteSize: 11,
  createdAt: Date.now(), expiresAt: Date.now() + 300_000,
  ...a,
});

describe("AgentApprovalCard", () => {
  it("命令被截断过时禁用「允许」——你看到的不是将执行的", () => {
    const kai = vi.fn();
    render(
      <AgentApprovalCard
        req={shen({ inputTruncated: true, originalByteSize: 90_000 })}
        onDecide={kai}
      />,
    );
    const btn = screen.getByRole("button", { name: "允许" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    fireEvent.click(btn);
    expect(kai).not.toHaveBeenCalled();
    expect(screen.getByText(/已被截断/)).toBeTruthy();
  });

  it("Agent 自撰的文本默认折叠，且标注了来源", () => {
    render(<AgentApprovalCard req={shen()} onDecide={() => undefined} />);
    const det = screen.getByText("由 Agent 生成，非系统信息") as HTMLDetailsElement;
    expect(det.tagName).toBe("SUMMARY");
    expect((det.parentElement as HTMLDetailsElement).open).toBe(false);
  });

  it("收口后进入不可交互终态，并显示是谁在什么时候决定的", () => {
    const kai = vi.fn();
    render(
      <AgentApprovalCard
        req={shen()}
        onDecide={kai}
        resolution={{
          requestId: "r-1", decision: "user_deny", autoDecided: false,
          autoReason: null, replayed: false, at: Date.now(),
        }}
      />,
    );
    expect(screen.queryByRole("button", { name: "拒绝" })).toBeNull();
    expect(screen.getByText("拒绝")).toBeTruthy();
    expect(screen.getByText(/已于/)).toBeTruthy();
  });

  it("409 already_resolved 把服务端说的历史决定显示出来", () => {
    render(
      <AgentApprovalCard
        req={shen()}
        onDecide={() => undefined}
        conflict="该审批请求已于 10 分钟前自动拒绝，你的批准未生效"
      />,
    );
    expect(screen.getByText(/自动拒绝，你的批准未生效/)).toBeTruthy();
  });

  it("危险命令要点两次才真放行", () => {
    const kai = vi.fn();
    render(<AgentApprovalCard req={shen({ toolInput: { command: "rm -rf /" } })} onDecide={kai} />);
    const btn = () => screen.getByRole("button", { name: /^(允许|确认放行这条危险命令)$/ }) as HTMLButtonElement;
    fireEvent.click(btn());
    expect(kai).not.toHaveBeenCalled();
    fireEvent.click(btn());
    expect(kai).toHaveBeenCalledWith("allow");
  });

  it("y / n 快捷键只在卡片拿到焦点时生效", () => {
    const kai = vi.fn();
    const { container } = render(<AgentApprovalCard req={shen()} onDecide={kai} />);
    const card = container.querySelector(".apr") as HTMLDivElement;
    fireEvent.focus(card);
    fireEvent.keyDown(card, { key: "n" });
    expect(kai).toHaveBeenCalledWith("deny");
  });

  it("没焦点时 y / n 不触发——否则会把整页的按键吃掉", () => {
    const kai = vi.fn();
    const { container } = render(<AgentApprovalCard req={shen()} onDecide={kai} />);
    const card = container.querySelector(".apr") as HTMLDivElement;
    fireEvent.keyDown(card, { key: "y" });
    expect(kai).not.toHaveBeenCalled();
  });
});
