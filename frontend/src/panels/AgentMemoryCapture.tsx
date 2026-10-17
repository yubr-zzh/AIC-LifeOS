import { useEffect, useState } from "react";
import {
  listAgentEvidence,
  proposeAgentMemoryCandidate,
  type AgentEvidence,
} from "../api/client";

export function AgentMemoryCapture({ sessionId, onCandidateCreated, onClose }: {
  sessionId: string;
  onCandidateCreated?: () => void;
  onClose?: () => void;
}) {
  const [items, setItems] = useState<AgentEvidence[]>([]);
  const [selected, setSelected] = useState("");
  const [claim, setClaim] = useState("");
  const [projectId, setProjectId] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try {
      const rows = await listAgentEvidence(sessionId);
      setItems(rows.slice(-5).reverse());
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };

  useEffect(() => {
    void refresh();
    setSelected("");
    setClaim("");
  }, [sessionId]);

  const submit = async () => {
    if (!selected || !claim.trim() || !projectId.trim()) {
      setMessage("请选择执行结果，并填写认知和稳定的项目 ID。");
      return;
    }
    setBusy(true);
    try {
      await proposeAgentMemoryCandidate(selected, claim.trim(), projectId.trim());
      setMessage("已提交为记忆候选，等待后续审核入口接入。");
      setClaim("");
      onCandidateCreated?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return <section className="agent-memory-capture">
    <div className="agent-memory-head">
      <strong>从执行结果提炼记忆</strong>
      <div>
        <button type="button" className="btn-ghost sm" onClick={() => void refresh()}>刷新结果</button>
        {onClose ? <button type="button" className="agent-memory-close" aria-label="关闭记忆面板" title="关闭记忆面板" onClick={onClose}>×</button> : null}
      </div>
    </div>
    {items.length === 0 ? <p>此会话还没有可提炼的结果。</p> : items.map((item) =>
      <label key={item.id} style={{ display: "block", marginTop: 8 }}>
        <input type="radio" name={`evidence-${sessionId}`} value={item.id}
          checked={selected === item.id} onChange={() => setSelected(item.id)} />
        <span style={{ whiteSpace: "pre-wrap" }}>{item.summary}</span>
      </label>,
    )}
    {selected ? <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
      <input value={projectId} onChange={(event) => setProjectId(event.target.value)}
        placeholder="稳定的项目 ID（必填）" />
      <textarea value={claim} onChange={(event) => setClaim(event.target.value)} rows={3}
        placeholder="手动写下一条长期有用的认知" />
      <button type="button" className="btn-ghost sm" disabled={busy}
        onClick={() => void submit()}>提交候选，等待审核</button>
    </div> : null}
    {message ? <p role="status">{message}</p> : null}
  </section>;
}
