import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type {
  ModelProfile,
  ModelProfileInput,
  ModelProtocol,
} from "../api/types";
import type { Store } from "../state/store";
import { IconApprove, IconChevron, IconKey, IconPlus, IconSettings, IconSpark } from "../components/Icons";

interface Props {
  store: Store;
  disabled?: boolean;
}

const protocolLabel: Record<ModelProtocol, string> = {
  mock: "本地",
  openai: "OpenAI 兼容",
  anthropic: "Anthropic",
};

function initials(profile: ModelProfile): string {
  const source = profile.provider_label || profile.name || "AI";
  return source.replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, "").slice(0, 2).toUpperCase() || "AI";
}

function isReady(profile: ModelProfile): boolean {
  if (profile.protocol === "mock" || profile.has_api_key) return true;
  if (["ollama", "custom"].includes(profile.provider)) return true;
  try {
    const hostname = new URL(profile.base_url).hostname;
    return hostname === "127.0.0.1" || hostname === "localhost";
  } catch {
    return false;
  }
}

export function ModelSwitcher({ store, disabled = false }: Props) {
  const catalog = store.state.modelCatalog;
  const active = catalog.profiles.find((profile) => profile.id === catalog.active_profile_id);
  const [open, setOpen] = useState(false);
  const [editor, setEditor] = useState<ModelProfile | "new" | null>(null);
  const [switching, setSwitching] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const choose = async (profileId: string) => {
    if (profileId === catalog.active_profile_id) {
      setOpen(false);
      return;
    }
    setSwitching(profileId);
    setError(null);
    try {
      await store.activateModel(profileId);
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSwitching(null);
    }
  };

  return (
    <>
      <div className="model-switcher" ref={root}>
        <button
          type="button"
          className="model-trigger"
          onClick={() => setOpen((value) => !value)}
          disabled={disabled}
          aria-haspopup="dialog"
          aria-expanded={open}
          title={active ? `${active.provider_label} · ${active.model}` : "选择模型"}
        >
          <span className="model-trigger-mark">{active ? initials(active) : <IconSpark size={12} />}</span>
          <span className="model-trigger-copy">
            <strong>{active?.name ?? "选择模型"}</strong>
            <small>{active?.model ?? "连接主流大模型"}</small>
          </span>
          <IconChevron size={12} className={`model-chevron ${open ? "open" : ""}`} />
        </button>

        {open ? (
          <div className="model-popover" role="dialog" aria-label="切换模型">
            <div className="model-popover-head">
              <div>
                <strong>模型与 API</strong>
                <span>选择本对话要使用的模型</span>
              </div>
              <span className="model-local-badge">本机配置</span>
            </div>
            <div className="model-option-list">
              {catalog.profiles.length === 0 ? (
                <div className="model-option-empty">还没有读取到模型配置</div>
              ) : catalog.profiles.map((profile) => {
                const selected = profile.id === catalog.active_profile_id;
                const ready = isReady(profile);
                return (
                  <button
                    type="button"
                    role="menuitemradio"
                    aria-checked={selected}
                    className={`model-option ${selected ? "selected" : ""}`}
                    key={profile.id}
                    onClick={() => void choose(profile.id)}
                    disabled={switching !== null}
                  >
                    <span className="model-option-mark">{initials(profile)}</span>
                    <span className="model-option-copy">
                      <strong>{profile.name}</strong>
                      <small>{profile.provider_label} · {profile.model}</small>
                    </span>
                    <span className={`model-ready ${ready ? "ready" : "missing"}`}>
                      {switching === profile.id ? "…" : ready ? "可用" : "待配置"}
                    </span>
                    {selected ? <IconApprove size={13} /> : null}
                  </button>
                );
              })}
            </div>
            {error ? <div className="model-error">{error}</div> : null}
            <div className="model-popover-actions">
              <button type="button" className="model-add-button" onClick={() => { setEditor("new"); setOpen(false); }}>
                <IconPlus size={13} /> 连接新模型
              </button>
              <button
                type="button"
                className="model-edit-button"
                onClick={() => { if (active) { setEditor(active); setOpen(false); } }}
                disabled={!active}
              >
                <IconSettings size={13} /> 配置
              </button>
            </div>
          </div>
        ) : null}
      </div>

      {editor ? (
        <ModelEditor
          store={store}
          profile={editor === "new" ? undefined : editor}
          onClose={() => setEditor(null)}
        />
      ) : null}
    </>
  );
}

interface EditorProps {
  store: Store;
  profile?: ModelProfile;
  onClose: () => void;
}

function ModelEditor({ store, profile, onClose }: EditorProps) {
  const presets = store.state.modelCatalog.presets;
  const initialPreset = presets.find((item) => item.id === profile?.provider)
    ?? presets.find((item) => item.id === "deepseek")
    ?? presets[0];
  const [draft, setDraft] = useState<ModelProfileInput>(() => ({
    id: profile?.id,
    name: profile?.name ?? initialPreset?.label ?? "新模型",
    provider: profile?.provider ?? initialPreset?.id ?? "custom",
    protocol: profile?.protocol ?? initialPreset?.protocol ?? "openai",
    base_url: profile?.base_url ?? initialPreset?.base_url ?? "",
    model: profile?.model ?? initialPreset?.models[0] ?? "",
    models: profile?.models ?? initialPreset?.models ?? [],
    enabled: profile?.enabled ?? true,
  }));
  const [modelsText, setModelsText] = useState((profile?.models ?? initialPreset?.models ?? []).join(", "));
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [busy, setBusy] = useState<"save" | "test" | "delete" | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const isMock = draft.protocol === "mock";
  const selectedPreset = presets.find((item) => item.id === draft.provider);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose]);

  const patch = (next: Partial<ModelProfileInput>) => setDraft((current) => ({ ...current, ...next }));

  const selectProvider = (providerId: string) => {
    const preset = presets.find((item) => item.id === providerId);
    if (!preset) return;
    const nextModels = preset.models;
    patch({
      provider: preset.id,
      protocol: preset.protocol,
      base_url: preset.base_url,
      model: nextModels[0] ?? "",
      models: nextModels,
      name: profile ? profile.name : preset.label,
    });
    setModelsText(nextModels.join(", "));
    setMessage(null);
  };

  const normalized = (): ModelProfileInput => {
    const models = modelsText
      .split(/[\n,]/)
      .map((value) => value.trim())
      .filter(Boolean);
    if (draft.model && !models.includes(draft.model)) models.unshift(draft.model);
    return { ...draft, models };
  };

  const save = async (event?: FormEvent) => {
    event?.preventDefault();
    setBusy("save");
    setMessage(null);
    try {
      const payload = { ...normalized(), api_key: apiKey, clear_api_key: clearKey };
      if (profile) await store.updateModel(profile.id, payload);
      else await store.createModel(payload);
      setMessage({ kind: "ok", text: profile ? "模型配置已更新" : "模型已连接并设为当前模型" });
      window.setTimeout(onClose, 450);
    } catch (err) {
      setMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  };

  const test = async () => {
    setBusy("test");
    setMessage(null);
    try {
      const result = await store.testModel({
        ...normalized(),
        api_key: apiKey,
        clear_api_key: clearKey,
      });
      setMessage({
        kind: "ok",
        text: `连接成功 · ${result.model ?? draft.model} · ${result.latency_ms} ms${result.preview ? ` · ${result.preview}` : ""}`,
      });
    } catch (err) {
      setMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    if (!profile || !window.confirm(`删除“${profile.name}”的本地 API 配置？`)) return;
    setBusy("delete");
    setMessage(null);
    try {
      await store.deleteModel(profile.id);
      onClose();
    } catch (err) {
      setMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
      setBusy(null);
    }
  };

  return (
    <div className="model-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
      <form className="model-editor" onSubmit={(event) => void save(event)} role="dialog" aria-modal="true" aria-labelledby="model-editor-title">
        <div className="model-editor-head">
          <div>
            <span className="model-editor-kicker">{profile ? "模型配置" : "连接 API"}</span>
            <h2 id="model-editor-title">{profile ? `编辑 ${profile.name}` : "添加主流大模型"}</h2>
            <p>像 CCswitch 一样保存多个端点，在输入框一键切换。</p>
          </div>
          <button type="button" className="model-editor-close" onClick={onClose} disabled={busy !== null} aria-label="关闭模型配置">×</button>
        </div>

        <div className="model-editor-body">
          <section className="model-editor-section">
            <div className="model-editor-section-title"><span>1</span><div><strong>选择供应商</strong><small>内置主流模型预设，也可以连接自定义端点</small></div></div>
            <div className="model-preset-grid">
              {presets.map((preset) => (
                <button
                  type="button"
                  key={preset.id}
                  className={draft.provider === preset.id ? "selected" : ""}
                  onClick={() => selectProvider(preset.id)}
                >
                  <strong>{preset.label}</strong>
                  <small>{protocolLabel[preset.protocol]}</small>
                </button>
              ))}
            </div>
            {selectedPreset ? <p className="model-preset-help">{selectedPreset.description}</p> : null}
          </section>

          <section className="model-editor-section">
            <div className="model-editor-section-title"><span>2</span><div><strong>连接参数</strong><small>API Key 只保存在本机 .lifeos/models.json</small></div></div>
            <div className="model-form-grid">
              <label className="model-field">
                <span>配置名称</span>
                <input value={draft.name} onChange={(event) => patch({ name: event.target.value })} placeholder="例如 DeepSeek 主力" required />
              </label>
              <label className="model-field">
                <span>模型 ID</span>
                <input value={draft.model} onChange={(event) => patch({ model: event.target.value })} placeholder="例如 deepseek-chat" required={!isMock} />
              </label>
              <label className="model-field model-field-wide">
                <span>API Base URL</span>
                <input value={draft.base_url} onChange={(event) => patch({ base_url: event.target.value })} placeholder="https://api.example.com/v1" required={!isMock} disabled={isMock} />
              </label>
              <label className="model-field model-field-wide">
                <span>API Key {profile?.has_api_key ? <em>已保存 {profile.api_key_hint}</em> : null}</span>
                <div className="model-key-row">
                  <IconKey size={14} />
                  <input
                    type="password"
                    autoComplete="off"
                    value={apiKey}
                    onChange={(event) => { setApiKey(event.target.value); setClearKey(false); }}
                    placeholder={isMock ? "本地模型不需要" : profile?.has_api_key ? "留空继续使用已保存的 Key" : selectedPreset?.api_key_required ? "输入 API Key" : "本地服务可留空"}
                    disabled={isMock}
                  />
                </div>
              </label>
              <label className="model-field model-field-wide">
                <span>可选模型列表 <em>用逗号分隔，仅用于快捷选择</em></span>
                <input value={modelsText} onChange={(event) => setModelsText(event.target.value)} placeholder="gpt-4.1, gpt-4o" />
              </label>
            </div>
            {profile?.has_api_key ? (
              <button type="button" className={`model-clear-key ${clearKey ? "active" : ""}`} onClick={() => { setClearKey((value) => !value); setApiKey(""); }}>
                {clearKey ? "保存后将清除 API Key" : "清除已保存的 API Key"}
              </button>
            ) : null}
          </section>
        </div>

        {message ? <div className={`model-editor-message ${message.kind}`}>{message.text}</div> : null}

        <div className="model-editor-footer">
          <div className="model-editor-footer-left">
            {profile && !profile.builtin ? (
              <button type="button" className="model-delete-button" onClick={() => void remove()} disabled={busy !== null}>
                {busy === "delete" ? "删除中…" : "删除配置"}
              </button>
            ) : <span className="model-security-note">Key 不会返回给前端，仅在发送请求时由本机后端读取。</span>}
          </div>
          <div className="model-editor-footer-right">
            <button type="button" className="model-test-button" onClick={() => void test()} disabled={busy !== null}>
              {busy === "test" ? "测试中…" : "测试连接"}
            </button>
            <button type="submit" className="model-save-button" disabled={busy !== null || !draft.name.trim() || (!isMock && (!draft.model.trim() || !draft.base_url.trim()))}>
              {busy === "save" ? "保存中…" : profile ? "保存修改" : "连接并启用"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
