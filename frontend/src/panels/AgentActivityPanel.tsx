import { useEffect, useState } from "react";
import { getEvents } from "../api/client";
import type { EventRecord } from "../state/store";

/** 7.7.2 的六个展示旁路 kind。字段全部枚举过，不含任何 Agent 文本，
 *  所以这个面板不存在「把 Agent 输出显示在页面上」的风险。 */
export const QIAO_JIE_KIND = [
  "bridge.connected",
  "bridge.disconnected",
  "session.created",
  "session.closed",
  "permission.resolved",
  "agent.crashed",
] as const;

const BIAO_SHI: Record<string, string> = {
  "bridge.connected": "Bridge 已启动",
  "bridge.disconnected": "Bridge 已关闭",
  "session.created": "新建会话",
  "session.closed": "会话关闭",
  "permission.resolved": "审批有结果",
  "agent.crashed": "Agent 进程异常",
};

const ZHOU_QI = 8000;
const MAX_VISIBLE = 20;

function shi_jian(s: string): string {
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return "--:--:--";
  return d.toTimeString().slice(0, 8);
}

function xian_shi(a: unknown): string {
  if (typeof a === "object" && a !== null) {
    try { return JSON.stringify(a); } catch { return String(a); }
  }
  return String(a);
}

export function AgentActivityPanel() {
  const [events, setEvents] = useState<EventRecord[] | null>(null);
  const [cuo, setCuo] = useState<string | null>(null);

  useEffect(() => {
    let huo = true;
    const lai = async () => {
      try {
        const r = await getEvents();
        if (!huo) return;
        setEvents(r.events.filter((e) => (QIAO_JIE_KIND as readonly string[]).includes(e.type)));
        setCuo(null);
      } catch (e) {
        if (huo) setCuo(e instanceof Error ? e.message : String(e));
      }
    };
    void lai();
    const ji = setInterval(() => void lai(), ZHOU_QI);
    return () => { huo = false; clearInterval(ji); };
  }, []);

  // 最多展示 20 条；新事件在前面（reverse）
  const lie = (events ?? []).slice(-MAX_VISIBLE).reverse();

  return (
    <section className="ags-activity" aria-label="Agent 活动">
      <header className="ags-head">
        <div>
          <span className="block-kicker">Agent 活动</span>
          <h2>本机 Agent 最近的 20 条旁路事件</h2>
        </div>
        <span className="block-meta">bridge.localbus · 7.7.2 · 每 {ZHOU_QI / 1000}s 刷新</span>
      </header>
      {cuo ? (
        <div className="state-empty">连不上主服务：{cuo}</div>
      ) : lie.length === 0 ? (
        <div className="state-empty">
          {events === null ? "正在读取…" : "还没有 Agent 活动。启动 Bridge 并建一个会话后，这里会记下发生了什么。"}
        </div>
      ) : (
        <ol className="ags-activity-list" role="list">
          {lie.map((e) => (
            <li key={e.id} className="ags-activity-row">
              <time className="mono ags-activity-time">{shi_jian(e.created_at)}</time>
              <span className="ags-activity-kind">
                <span className="mono">{e.type}</span>
                <span className="dim"> · {BIAO_SHI[e.type] ?? e.type}</span>
              </span>
              {Object.entries(e.payload ?? {}).length > 0 ? (
                <span className="ags-activity-payload">
                  {Object.entries(e.payload ?? {}).map(([k, v]) => (
                    <span key={k}>
                      <span className="muted">{k}=</span>
                      <span>{xian_shi(v)}</span>
                    </span>
                  ))}
                </span>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
