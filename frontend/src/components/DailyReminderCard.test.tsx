import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DailyReminderCard, reminderIndex } from "./DailyReminderCard";

describe("DailyReminderCard", () => {
  it("20 组提醒按天轮换，第 21 天回到第 1 组", () => {
    const indexes = Array.from({ length: 20 }, (_, day) => reminderIndex(new Date(2026, 0, 1 + day)));
    expect(new Set(indexes).size).toBe(20);
    expect(reminderIndex(new Date(2026, 0, 21))).toBe(indexes[0]);
  });

  it("在今日概览显示今日提醒和轮换序号", () => {
    render(<DailyReminderCard date={new Date(2026, 0, 1)} />);
    expect(screen.getByText("今日提醒")).toBeTruthy();
    expect(screen.getByText(/第 1/)).toBeTruthy();
  });
});