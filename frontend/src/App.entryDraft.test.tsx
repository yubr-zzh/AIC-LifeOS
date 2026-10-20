import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StructuredEntry } from "./api/types";

vi.mock("./api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/client")>();
  return {
    ...actual,
    listEntries: vi.fn(),
    saveEntry: vi.fn(),
  };
});

import { listEntries, saveEntry } from "./api/client";
import { useEntryDraft } from "./App";

const listMock = vi.mocked(listEntries);
const saveMock = vi.mocked(saveEntry);

function row(id: string, content: string, kind: StructuredEntry["kind"] = "daily_plan"): StructuredEntry {
  const now = "2026-10-20T08:00:00.000Z";
  return {
    id,
    kind,
    entry_date: "2026-10-20",
    title: "",
    content,
    mood: null,
    metadata: {},
    created_at: now,
    updated_at: now,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  listMock.mockResolvedValue([]);
});

describe("useEntryDraft", () => {
  it("保存后立即进入历史，并且“新建”后再保存会产生第二条记录", async () => {
    let seq = 0;
    saveMock.mockImplementation(async (payload) => row(
      payload.id ?? `new-${++seq}`,
      payload.content ?? "",
      payload.kind,
    ));

    const { result } = renderHook(() => useEntryDraft("daily_plan", {}));
    await waitFor(() => expect(result.current.loaded).toBe(true));

    act(() => result.current.setContent("第一条规划"));
    await act(async () => { await result.current.save(); });

    expect(result.current.entries).toHaveLength(1);
    expect(result.current.saveFeedback?.text).toContain("已保存到本地 SQLite");

    act(() => result.current.startNew());
    expect(result.current.id).toBeUndefined();
    act(() => result.current.setContent("第二条规划"));
    await act(async () => { await result.current.save(); });

    expect(result.current.entries).toHaveLength(2);
    expect(saveMock.mock.calls[1][0].id).toBeUndefined();
    expect(result.current.entries.map((entry) => entry.content)).toContain("第一条规划");
    expect(result.current.entries.map((entry) => entry.content)).toContain("第二条规划");
  });

  it("保存失败时在页面状态里给出错误提示，而不是静默失败", async () => {
    saveMock.mockRejectedValue(new Error("disk full"));
    const { result } = renderHook(() => useEntryDraft("daily_review", {}));
    await waitFor(() => expect(result.current.loaded).toBe(true));

    act(() => result.current.setContent("这次复盘会保存失败"));
    await act(async () => { await result.current.save(); });

    expect(result.current.saveFeedback).toEqual({
      tone: "error",
      text: "保存失败：disk full",
    });
    expect(result.current.saving).toBe(false);
  });

  it("点击历史记录会载入其内容，历史列表本身不被覆盖", async () => {
    listMock.mockResolvedValue([
      row("old-1", "旧的规划", "daily_plan"),
      row("old-2", "更早的规划", "daily_plan"),
    ]);
    const { result } = renderHook(() => useEntryDraft("daily_plan", {}));
    await waitFor(() => expect(result.current.loaded).toBe(true));

    act(() => result.current.openEntry(row("old-2", "更早的规划", "daily_plan")));

    expect(result.current.id).toBe("old-2");
    expect(result.current.content).toBe("更早的规划");
    expect(result.current.entries).toHaveLength(2);
  });
});
