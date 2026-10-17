import React, { useEffect, useState } from "react";
import { getEvents } from "../api/client";
import type { EventRecord } from "../state/store";
import { Panel } from "../components/Panel";

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

function shi_jian(s: string): string {
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return "--:--:--";
  return d.toTimeString().slice(0, 8);
}

function xian_shi(a: unknown): string {
  return typeof a === "object" && a !== null ? JSON.stringify(a) : String(a);
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

  const lie = (events ?? []).slice(-20).reverse();

  return (
    <Panel title="Agent 活动" subtitle="最近 20 条 · 每 8 秒自动刷新" dense className="agent-activity-panel">
      {cuo ? (
        <div className="state-empty">连不上主服务：{cuo}</div>
      ) : lie.length === 0 ? (
        <div className="state-empty">
          {events === null ? "正在读取…" : "还没有 Agent 活动。启动 Bridge 并建一个会话后，这里会记下发生了什么。"}
        </div>
      ) : (
        <table className="table">
          <thead>
            <tr><th>时间</th><th>事件</th><th>详情</th></tr>
          </thead>
          <tbody>
            {lie.map((e) => (
              <tr key={e.id}>
                <td className="mono dim">{shi_jian(e.created_at)}</td>
                <td>
                  {/* 原始 kind 原样显示：它是排查时的检索键，中文标签只是给人看的。
                      `bridge.connected` 这类字符串必须能被直接读到。 */}
                  <span className="mono">{e.type}</span>
                  <span className="dim"> · {BIAO_SHI[e.type] ?? e.type}</span>
                </td>
                <td className="mono dim">
                  {/* 键和值各自成一个元素。拼成一整句的话用户得自己找，
                      而且「这条事件的 decision 是什么」这种断言没法直接写。 */}
                  {Object.entries(e.payload ?? {}).length === 0 ? (
                    <span>（无附加信息）</span>
                  ) : (
                    Object.entries(e.payload ?? {}).map(([k, v]) => (
                      <span key={k} style={{ marginRight: 12 }}>
                        <span className="muted">{k}=</span>
                        <span>{xian_shi(v)}</span>
                      </span>
                    ))
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
