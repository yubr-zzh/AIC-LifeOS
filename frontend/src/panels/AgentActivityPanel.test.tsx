import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { AgentActivityPanel, QIAO_JIE_KIND } from "./AgentActivityPanel";
import * as client from "../api/client";
import type { EventRecord } from "../state/store";

const shi = (a: Partial<EventRecord> & { type: string }): EventRecord => ({
  id: `e-${a.type}`, payload: {}, status: "done", attempts: 0,
  created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  ...a,
  // type 显式写在展开之后：写在前面 tsc 会判为「指定了两次、前者被覆盖」(TS2783)。
  // 谁在前谁在后都不影响结果，因为 a.type 本来就是必填的。
  type: a.type,
});

function zhuang(a: EventRecord[]) {
  vi.spyOn(client, "getEvents").mockResolvedValue({ events: a, source: "backend" });
  return render(<AgentActivityPanel />);
}

describe("AgentActivityPanel", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("只显示桥接六类，其他事件一条都不出现", async () => {
    zhuang([shi({ type: "session.created", payload: { sessionId: "s-1", agentId: "claude-code" } }),
            shi({ type: "chat.turn" }),
            shi({ type: "skill.detected" })]);
    expect(await screen.findByText("session.created")).toBeTruthy();
    expect(screen.queryByText("chat.turn")).toBeNull();
    expect(screen.queryByText("skill.detected")).toBeNull();
  });

  it("六类都要能被渲染——少一类用户就看不到那件事发生了", async () => {
    zhuang(QIAO_JIE_KIND.map((k, i) => shi({ id: `e-${i}`, type: k })));
    for (const k of QIAO_JIE_KIND) {
      expect(await screen.findByText(k)).toBeTruthy();
    }
  });

  it("detail 里的字段原样显示，不做任何加工", async () => {
    zhuang([shi({ type: "permission.resolved",
                  payload: { requestId: "toolu_01", decision: "user_allow", replayed: true } })]);
    // 每个值单独成元素：拼成一整句的话，用户要在里面找，测试也定位不到
    expect(await screen.findByText("toolu_01")).toBeTruthy();
    expect(screen.getByText("user_allow")).toBeTruthy();
    expect(screen.getByText("true")).toBeTruthy();
  });

  it("一条都没有时说的是「还没有活动」，不是空白", async () => {
    zhuang([]);
    expect(await screen.findByText(/还没有/)).toBeTruthy();
  });

  it("取数失败不崩，给一句看得懂的提示", async () => {
    vi.spyOn(client, "getEvents").mockRejectedValue(new Error("连接失败"));
    render(<AgentActivityPanel />);
    expect(await screen.findByText(/连不上/)).toBeTruthy();
  });

  it("最多展示最近 20 条，更早的记录不铺满页面", async () => {
    zhuang(Array.from({ length: 25 }, (_, index) => shi({
      id: `e-${index}`,
      type: "session.created",
      payload: { marker: `m-${index}` },
    })));
    expect(await screen.findByText("m-24")).toBeTruthy();
    expect(screen.queryByText("m-0")).toBeNull();
    expect(screen.getByText("m-5")).toBeTruthy();
  });
  it("每隔一段时间自己刷新一次，不用进后台页面", async () => {
    const du = vi.spyOn(client, "getEvents")
      .mockResolvedValue({ events: [], source: "backend" });
    render(<AgentActivityPanel />);
    await waitFor(() => expect(du).toHaveBeenCalledTimes(1));
    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(du.mock.calls.length).toBeGreaterThan(1);
  });
});
