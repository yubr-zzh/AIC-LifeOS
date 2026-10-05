import { describe, expect, it } from "vitest";
import { sendChat } from "./client";

describe("sendChat", () => {
  it("sends the selected Agent session and project scope to LifeOS", async () => {
    let payload: unknown;
    const fetchImpl = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      payload = JSON.parse(String(init?.body));
      return new Response(JSON.stringify({ trace_id: "trace-1", response: "ok" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }) as typeof fetch;

    await sendChat("继续", { baseUrl: "http://localhost:8765", fetchImpl },
      { kind: "project", project_id: "lifeos" }, "agent-session-1");

    expect(payload).toEqual({
      message: "继续",
      memory_scope: { kind: "project", project_id: "lifeos" },
      session_id: "agent-session-1",
    });
  });
});
