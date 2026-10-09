import React, { useMemo, useState } from "react";
import { MAX_INSTRUCTION_CHARS, type DelegationItem, type DelegationPlan } from "../api/agentTypes";

/** 上行字节预算。超了整批 413，用户勾的指令会全丢，所以前端先拦一道。 */
const XINGE = 180 * 1024;

interface Props {
  plan: DelegationPlan;
  /** 没有连接时也要能改计划，只是发不出去。 */
  canSend: boolean;
  onChange: (a: DelegationPlan) => void;
  onSend: (a: string[]) => void;
  onOpenPanel: () => void;
}

/**
 * R-V3 依赖闭包：取消 a 之后，所有（传递）依赖它的条目一起取消，并写明原因。
 * 就地改 a —— 它已经是新数组了。
 */
export function lianDai(a: DelegationItem[], b: string): void {
  const qu = new Set<string>([b]);
  let bian = true;
  while (bian) {
    bian = false;
    for (const it of a) {
      if (!it.enabled || !it.dependsOn.some((d) => qu.has(d))) continue;
      qu.add(it.itemId);
      it.enabled = false;
      it.note = `因依赖 ${it.dependsOn.filter((d) => qu.has(d)).join("、")} 已取消`;
      bian = true;
    }
  }
}

export function DelegationCard({ plan, canSend, onChange, onSend, onOpenPanel }: Props) {
  const [bian, setBian] = useState(false);

  const xuan = useMemo(() => plan.items.filter((i) => i.enabled), [plan.items]);
  const zong = useMemo(
    () => xuan.reduce((a, i) => a + new TextEncoder().encode(i.instruction).length, 0),
    [xuan],
  );
  const chao = zong > XINGE;
  const fa = plan.status === "draft" || plan.status === "approved";

  const qiao = (a: string) => {
    const jin = plan.items.find((i) => i.itemId === a);
    const next = plan.items.map((i) =>
      i.itemId === a ? { ...i, enabled: !i.enabled, note: undefined } : { ...i },
    );
    if (!jin?.enabled) lianDai(next, a);
    onChange({ ...plan, items: next });
  };

  const gai = (a: string, b: string) => {
    onChange({
      ...plan,
      items: plan.items.map((i) => (i.itemId === a ? { ...i, instruction: b } : i)),
    });
  };

  return (
    <div className="dlg">
      <div className="dlg-head">
        <span className="card-kicker">委派计划</span>
        <span className="dlg-status mono">{plan.status}</span>
        {plan.degraded ? <span className="pill pending sm"><span className="dot" />自动规划不可用，已降级为单条</span> : null}
      </div>
      <p className="dlg-sum">{plan.summary}</p>

      <ol className="dlg-items">
        {plan.items.map((i) => (
          <li key={i.itemId} className={`dlg-item ${i.enabled ? "" : "off"}`}>
            <label className="dlg-check">
              <input type="checkbox" checked={i.enabled} onChange={() => qiao(i.itemId)} disabled={!fa} />
              <span className="mono">{i.itemId}</span>
            </label>
            <div className="dlg-item-main">
              {i.editable && fa ? (
                <textarea
                  className="dlg-edit"
                  value={i.instruction}
                  rows={Math.min(6, Math.ceil(i.instruction.length / 60))}
                  onChange={(e) => gai(i.itemId, e.target.value)}
                />
              ) : (
                <p className="dlg-text">{i.instruction}</p>
              )}
              {i.note ? <p className="dlg-note">{i.note}</p> : null}
              {i.instruction.length > MAX_INSTRUCTION_CHARS ? (
                <p className="dlg-note err">
                  这条 {i.instruction.length} 字符，超过单条上限 {MAX_INSTRUCTION_CHARS}，发不出去。
                </p>
              ) : null}
            </div>
          </li>
        ))}
      </ol>

      {chao ? (
        <p className="dlg-note err">
          勾选的指令合计 {Math.round(zong / 1024)} KB，超过一次请求的 {Math.round(XINGE / 1024)} KB 上限。
          取消几条或改短后再发。
        </p>
      ) : null}

      <div className="dlg-foot">
        <span className="mono dim">已选 {xuan.length}/{plan.items.length} 条 · {Math.round(zong / 1024)} KB</span>
        <div className="dlg-btns">
          {!canSend ? (
            <button className="btn-ghost" onClick={onOpenPanel} title="先到「本地 Agent」页连接一个 Agent">
              先连接 Agent
            </button>
          ) : null}
          <button
            className="btn-allow"
            disabled={!fa || xuan.length === 0 || chao || bian}
            onClick={() => {
              setBian(true);
              onSend(xuan.map((i) => i.instruction));
            }}
          >
            {bian ? "已发送" : `把这 ${xuan.length} 条发给 Agent`}
          </button>
        </div>
      </div>
    </div>
  );
}
