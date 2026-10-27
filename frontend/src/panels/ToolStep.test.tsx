import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ToolStep } from "./ToolStep";
import type { AgentToolCall } from "../api/agentTypes";

const call = (a: Partial<AgentToolCall> = {}): AgentToolCall => ({
  toolUseId: "t-1",
  sessionId: "s-1",
  seq: 1,
  name: "Read",
  input: { file_path: "D:/a/b.ts" },
  state: { type: "completed", isError: false, durationMs: 320 },
  resultText: "file body",
  summary: "读取 b.ts",
  ...a,
});

describe("ToolStep", () => {
  it("completed 成功显示 ✓ 和耗时", () => {
    render(<ToolStep call={call()} />);
    expect(screen.getByText("读取 b.ts")).toBeTruthy();
    expect(screen.getByText("320ms")).toBeTruthy();
  });

  it("completed 失败默认展开，文字是红的", () => {
    render(<ToolStep call={call({
      state: { type: "completed", isError: true, durationMs: 12 },
      resultText: "命令退出码 1",
    })} />);
    expect(screen.getByText("失败")).toBeTruthy();
    expect(screen.getByText("命令退出码 1")).toBeTruthy();
  });

  it("awaiting_confirmation 强制展开且不可折叠", () => {
    const onLocate = vi.fn();
    render(<ToolStep call={call({
      name: "Bash",
      summary: "运行 npm test",
      input: { command: "npm test" },
      state: { type: "awaiting_confirmation", requestId: "r-1" },
      resultText: "",
    })} onLocateApproval={onLocate} />);
    expect(screen.getByText("等待你批准")).toBeTruthy();
    // 强制展开：输入已经可见（摘要行和 pre 都含 npm test）
    expect(screen.getAllByText(/npm test/).length).toBeGreaterThan(1);
    // 点击不是折叠，而是定位审批卡
    fireEvent.click(screen.getByRole("button"));
    expect(onLocate).toHaveBeenCalledWith("r-1");
  });

  it("streaming 时提示参数未生成完（展开后可见）", () => {
    render(<ToolStep call={call({
      state: { type: "streaming", partialInput: '{"file_path":"D:/a' },
      input: null,
      resultText: "",
    })} />);
    expect(screen.getByText("生成参数中")).toBeTruthy();
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText(/参数未生成完/)).toBeTruthy();
    expect(screen.getByText(/"file_path":"D:\/a/)).toBeTruthy();
  });

  it("cancelled 显示中文原因", () => {
    render(<ToolStep call={call({ state: { type: "cancelled", reason: "denied" } })} />);
    expect(screen.getByText("已拒绝")).toBeTruthy();
  });

  it("点击已完成行可以展开输入与结果", () => {
    render(<ToolStep call={call()} />);
    expect(screen.queryByText("file body")).toBeNull();
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("file body")).toBeTruthy();
  });
});
