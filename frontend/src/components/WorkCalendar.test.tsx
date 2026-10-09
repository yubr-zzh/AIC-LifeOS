import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import * as client from "../api/client";
import type { StructuredEntry } from "../api/types";
import { WorkCalendar } from "./WorkCalendar";

const today = new Date();
const localToday = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
const entry: StructuredEntry = {
  id: "diary-1", kind: "diary", entry_date: localToday,
  title: "A saved note", content: "A small moment worth remembering", metadata: {},
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

describe("WorkCalendar", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows saved entries for today and navigates to the matching page", async () => {
    vi.spyOn(client, "listEntries").mockImplementation(async (kind) => kind === "diary" ? [entry] : []);
    const onNavigate = vi.fn();
    render(<WorkCalendar onNavigate={onNavigate} />);

    await waitFor(() => expect(screen.getByText("A saved note")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "打开记录 →" }));
    expect(onNavigate).toHaveBeenCalledWith("diary");
  });

  it("shows a recoverable message when structured records cannot be loaded", async () => {
    vi.spyOn(client, "listEntries").mockRejectedValue(new Error("offline"));
    render(<WorkCalendar onNavigate={() => undefined} />);
    expect(await screen.findByRole("alert")).toBeTruthy();
  });
});
