import { useEffect, useState } from "react";
import {
  listAgentEvidence,
  proposeAgentMemoryCandidate,
  type AgentEvidence,
} from "../api/client";

export function AgentMemoryCapture({ sessionId, onCandidateCreated }: {
  sessionId: string;
  onCandidateCreated?: () => void;
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
      setMessage("已提交为记忆候选，请到系统后台的 Memory 面板审核。");
      setClaim("");
      onCandidateCreated?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <details className="agp-capture">
      <summary>
        提炼记忆
        {items.length > 0 ? <span className="agp-capture-n">{items.length}</span> : null}
      </summary>
      <div className="agp-capture-body">
        <div className="agp-capture-head">
          <span>从本轮执行结果里挑一条，写成长期有用的认知。</span>
          <button type="button" className="btn-ghost sm" onClick={() => void refresh()}>
            刷新
          </button>
        </div>
        {items.length === 0 ? (
          <p className="agp-capture-hint">还没有可提炼的结果。</p>
        ) : (
          items.map((item) => (
            <label key={item.id} className="agp-capture-item">
              <input type="radio" name={`evidence-${sessionId}`} value={item.id}
                checked={selected === item.id} onChange={() => setSelected(item.id)} />
              <span>{item.summary}</span>
            </label>
          ))
        )}
        {selected ? (
          <div className="agp-capture-form">
            <input value={projectId} onChange={(event) => setProjectId(event.target.value)}
              placeholder="稳定的项目 ID（必填）" />
            <textarea value={claim} onChange={(event) => setClaim(event.target.value)} rows={3}
              placeholder="手动写下一条长期有用的认知" />
            <button type="button" className="btn-ghost sm" disabled={busy}
              onClick={() => void submit()}>提交候选，等待审核</button>
          </div>
        ) : null}
        {message ? <p className="agp-capture-hint" role="status">{message}</p> : null}
      </div>
    </details>
  );
}
