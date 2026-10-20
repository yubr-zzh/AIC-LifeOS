import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/authClient", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/authClient")>();
  return {
    ...actual,
    authStatus: vi.fn(),
    listSessions: vi.fn(),
  };
});

import { authStatus, listSessions } from "../api/authClient";
import { AccountMenu } from "./AuthGate";

const statusMock = vi.mocked(authStatus);
const sessionsMock = vi.mocked(listSessions);

beforeEach(() => {
  vi.clearAllMocks();
  sessionsMock.mockResolvedValue([]);
});

describe("AccountMenu", () => {
  it("显示已保存头像，并提供修改头像与修改密码入口", async () => {
    statusMock.mockResolvedValue({
      initialized: true,
      authenticated: true,
      username: "admin",
      avatar: "data:image/jpeg;base64,AAAA",
      csrf: "csrf-1",
    });
    const { container } = render(<AccountMenu />);

    await waitFor(() => expect(container.querySelector(".avatar img")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "打开账户菜单" }));
    await waitFor(() => expect(statusMock).toHaveBeenCalledTimes(2));

    expect(screen.getByRole("button", { name: "修改头像" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "修改密码" })).toBeTruthy();
    expect(screen.queryByText("修改口令")).toBeNull();
  });
});
