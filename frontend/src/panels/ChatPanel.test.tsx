import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { Store } from "../state/store";
import { ChatPanel } from "./ChatPanel";

const message = (id: string, content: string) => ({
  id, role: "user" as const, content, created_at: new Date().toISOString(),
});

function dummyStore(): Store {
  return {
    state: {
      messages: [],
      loading: { chat: false },
      ui: { dataMode: "preview" },
    },
    dispatch: vi.fn(),
    sendMessage: vi.fn(),
    refreshAll: vi.fn(),
    submitRating: vi.fn(),
  } as unknown as Store;
}

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("ChatPanel 对话管理", () => {
  it("可以给当前对话重命名", async () => {
    localStorage.setItem("lifeos.chat.history.v1", JSON.stringify([
      { id: "c-1", title: "原对话", customTitle: true, updatedAt: new Date().toISOString(), messages: [message("m1", "内容")] },
    ]));
    vi.spyOn(window, "prompt").mockReturnValue("项目讨论");
    render(<ChatPanel store={dummyStore()} />);
    await waitFor(() => expect(screen.getAllByText("原对话").length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: "重命名对话：原对话" }));
    expect(screen.getAllByText("项目讨论").length).toBeGreaterThan(0);
  });

  it("可以选择文本文件并显示在输入框上方", async () => {
    const { container } = render(<ChatPanel store={dummyStore()} />);
    const file = new File(["附件内容"], "note.txt", { type: "text/plain" });
    Object.defineProperty(file, "text", { value: async () => "附件内容" });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(screen.getByText("note.txt")).toBeTruthy());
  });
});

describe("ChatPanel 对话内容精简", () => {
  it("不显示路由说明、回答类型、feedback 行和历史位置提示，复制按钮位于消息底部", async () => {
    const assistant = {
      id: "a-1",
      role: "assistant" as const,
      content: "这是一条回答",
      created_at: new Date().toISOString(),
      trace_id: "trace-1",
      execution: "succeeded" as const,
      decision: "self_plan" as const,
      decision_reason: "你选择了自规划模式。",
      agent_enabled: false,
      plan_steps: [{ id: 1, title: "读取相关资源", detail: "限于当前工作区" }],

    };
    const store = dummyStore();
    store.state.messages = [assistant];
    localStorage.setItem("lifeos.chat.history.v1", JSON.stringify([
      { id: "c-1", title: "回答测试", customTitle: true, updatedAt: new Date().toISOString(), messages: [assistant] },
    ]));

    const { container } = render(<ChatPanel store={store} />);
    await screen.findByText("这是一条回答");

    expect(screen.queryByText("为什么这样处理")).toBeNull();
    expect(screen.queryByText("文本回答")).toBeNull();
    expect(screen.queryByText("feedback")).toBeNull();
    expect(screen.queryByText("历史仅保存在此浏览器")).toBeNull();
    expect(container.querySelector(".context-dot")).toBeNull();
    const copy = screen.getByRole("button", { name: "复制" });
    expect(copy.parentElement?.className).toContain("assistant-message-foot");
  });
});

describe("ChatPanel 侧栏收起", () => {
  it("可以隐藏并恢复最近对话侧栏，并记住选择", async () => {
    render(<ChatPanel store={dummyStore()} />);
    const hide = screen.getByRole("button", { name: "隐藏对话历史" });
    fireEvent.click(hide);
    expect(screen.queryByRole("complementary", { name: "对话历史" })).toBeNull();
    expect(localStorage.getItem("lifeos.chat.historyCollapsed.v1")).toBe("1");
    fireEvent.click(screen.getByRole("button", { name: "显示对话历史" }));
    expect(screen.getByRole("complementary", { name: "对话历史" })).toBeTruthy();
  });
});

describe("ChatPanel 会话删除", () => {
  it("每个历史会话都有删除按钮，删除后从列表消失", async () => {
    localStorage.setItem("lifeos.chat.history.v1", JSON.stringify([
      { id: "c-1", title: "第一次对话", updatedAt: new Date().toISOString(), messages: [message("m1", "一")] },
      { id: "c-2", title: "第二次对话", updatedAt: new Date().toISOString(), messages: [message("m2", "二")] },
    ]));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ChatPanel store={dummyStore()} />);

    await waitFor(() => expect(screen.getByText("第二次对话")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "删除对话：第二次对话" }));
    expect(screen.queryByText("第二次对话")).toBeNull();
  });
});
