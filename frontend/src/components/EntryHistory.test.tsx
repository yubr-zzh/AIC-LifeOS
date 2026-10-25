import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { StructuredEntry } from "../api/types";
import { EntryHistory } from "./EntryHistory";

const row: StructuredEntry = {
  id: "e-1",
  kind: "daily_plan",
  entry_date: "2026-10-20",
  title: "",
  content: "完成今天的重点任务",
  mood: null,
  metadata: {},
  created_at: "2026-10-20T08:00:00.000Z",
  updated_at: "2026-10-20T08:00:00.000Z",
};

describe("EntryHistory", () => {
  it("历史记录可点击查看，并可显式新建下一条", () => {
    const onSelect = vi.fn();
    const onNew = vi.fn();
    render(<EntryHistory entries={[row]} onSelect={onSelect} onNew={onNew}
      heading="每日规划记录" newLabel="＋ 新建每日规划" />);

    expect(screen.getByText("每日规划记录")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /完成今天的重点任务/ }));
    expect(onSelect).toHaveBeenCalledWith(row);

    fireEvent.click(screen.getByRole("button", { name: "＋ 新建每日规划" }));
    expect(onNew).toHaveBeenCalledTimes(1);
  });
});
