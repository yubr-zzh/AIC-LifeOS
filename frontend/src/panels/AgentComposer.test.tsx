import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AgentComposer } from "./AgentComposer";

describe("AgentComposer", () => {
  it("尚未连接 Agent 时仍允许输入草稿，只禁用发送", () => {
    const onSend = vi.fn();
    render(<AgentComposer canSend={false} onSend={onSend} />);
    const box = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "先写好指令" } });
    expect(box.disabled).toBe(false);
    expect(box.value).toBe("先写好指令");
    const send = screen.getByRole("button", { name: "发送" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
  });

  it("连接后按 Enter 会发送内容，成功后清空输入", async () => {
    const onSend = vi.fn();
    render(<AgentComposer canSend onSend={onSend} />);
    const box = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "执行任务" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(onSend).toHaveBeenCalledWith("执行任务"));
    await waitFor(() => expect(box.value).toBe(""));
  });

  it("发送失败时保留输入内容并显示错误", async () => {
    const onSend = vi.fn().mockRejectedValue(new Error("网络失败"));
    render(<AgentComposer canSend onSend={onSend} />);
    const box = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "不要丢失这段话" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect((await screen.findByRole("alert")).textContent).toContain("网络失败");
    expect(box.value).toBe("不要丢失这段话");
  });
});
