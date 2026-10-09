import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ModelProviderSettings } from "./ModelProviderSettings";

const catalog = {
  active_profile_id: "mock",
  profiles: [{
    id: "mock", name: "Local demo", provider: "mock", provider_label: "LifeOS Mock",
    protocol: "mock", base_url: "", model: "lifeos-mock", models: ["lifeos-mock"],
    enabled: true, builtin: true, has_api_key: false, api_key_hint: "",
  }],
  presets: [{
    id: "openai", label: "OpenAI-compatible", protocol: "openai", base_url: "",
    models: [], api_key_required: true, description: "Test preset",
  }],
};

describe("ModelProviderSettings model discovery", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("fetches model IDs after URL and key are entered, then lets the user choose", async () => {
    let discoveryPayload: Record<string, unknown> | undefined;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/models" && !init?.method) {
        return new Response(JSON.stringify(catalog), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url === "/api/bridge/info") {
        return new Response(JSON.stringify({ csrf: "test-csrf" }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url === "/api/models/discover") {
        discoveryPayload = JSON.parse(String(init?.body));
        return new Response(JSON.stringify({ models: ["Agnes-2.5", "Agnes-2.5-thinking"] }), { status: 200, headers: { "content-type": "application/json" } });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ModelProviderSettings />);

    fireEvent.click(await screen.findByRole("button", { name: /添加 Provider/ }));
    fireEvent.change(screen.getByLabelText("API Base URL"), { target: { value: "https://models.example.test/v1" } });
    const apiKey = screen.getByLabelText("API Key");
    fireEvent.change(apiKey, { target: { value: "synthetic-key" } });
    fireEvent.blur(apiKey);

    const modelSelect = await screen.findByRole("combobox", { name: "选择模型" });
    await waitFor(() => expect(discoveryPayload).toMatchObject({
      base_url: "https://models.example.test/v1", api_key: "synthetic-key", protocol: "openai",
    }));
    fireEvent.change(modelSelect, { target: { value: "Agnes-2.5-thinking" } });
    expect((modelSelect as HTMLSelectElement).value).toBe("Agnes-2.5-thinking");
    expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/models/discover")).toBe(true);
  });

  it("shows a retryable error instead of leaving the model settings stuck loading", async () => {
    const fetchMock = vi.fn(async () => new Response(
      JSON.stringify({ error: { message: "model profile secret cannot be decrypted" } }),
      { status: 500, headers: { "content-type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetchMock);
    render(<ModelProviderSettings />);

    expect((await screen.findByRole("alert")).textContent).toContain("model profile secret cannot be decrypted");
    expect(screen.getByRole("button", { name: "重新加载" })).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
  });
});
