import { useCallback, useEffect, useRef, useState } from "react";

type Protocol = "mock" | "openai" | "anthropic";
interface Preset {
  id: string; label: string; protocol: Protocol; base_url: string;
  models: string[]; api_key_required: boolean; description: string;
}
interface Profile {
  id: string; name: string; provider: string; provider_label: string;
  protocol: Protocol; base_url: string; model: string; models: string[];
  enabled: boolean; builtin: boolean; has_api_key: boolean; api_key_hint: string;
  api_key_unavailable?: boolean;
}
interface Catalog { active_profile_id: string; profiles: Profile[]; presets: Preset[] }
interface Draft {
  id?: string; name: string; provider: string; protocol: Protocol;
  base_url: string; model: string; api_key: string; models: string[];
  has_api_key?: boolean; api_key_unavailable?: boolean; models_discovered?: boolean;
}

const EMPTY_DRAFT: Draft = { name: "", provider: "openai", protocol: "openai", base_url: "", model: "", api_key: "", models: [] };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  let csrfHeaders: Record<string, string> = {};
  if (method !== "GET") {
    const tokenResponse = await fetch("/api/bridge/info");
    if (!tokenResponse.ok) throw new Error("无法取得本机设置授权，请刷新页面后重试。");
    const tokenData = await tokenResponse.json() as { csrf?: string };
    if (!tokenData.csrf) throw new Error("本机设置授权不可用，请刷新页面后重试。");
    csrfHeaders = { "X-LifeOS-CSRF": tokenData.csrf };
  }
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...csrfHeaders, ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.error?.message || `请求失败（${response.status}）`);
  }
  return response.json() as Promise<T>;
}

export function ModelProviderSettings() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [loadingCatalog, setLoadingCatalog] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [discoveringModels, setDiscoveringModels] = useState(false);
  const [discoveryError, setDiscoveryError] = useState("");
  const discoveryInFlight = useRef(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const refresh = useCallback(async () => {
    setLoadingCatalog(true);
    setCatalogError("");
    try {
      const next = await request<Catalog>("/models");
      setCatalog(next);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setCatalogError(message);
      throw error;
    } finally {
      setLoadingCatalog(false);
    }
  }, []);

  useEffect(() => { void refresh().catch((error) => setNotice({ kind: "error", text: error.message })); }, [refresh]);

  const applyPreset = (provider: string) => {
    const preset = catalog?.presets.find((item) => item.id === provider);
    if (!preset || !draft) return;
    setDraft({ ...draft, provider, protocol: preset.protocol, base_url: preset.base_url,
      model: preset.models[0] ?? "", models: preset.models, models_discovered: false });
  };

  const openNew = () => {
    const preset = catalog?.presets.find((item) => item.id === "openai") ?? catalog?.presets[0];
    setDraft({ ...EMPTY_DRAFT, provider: preset?.id ?? "custom", protocol: preset?.protocol ?? "openai",
      base_url: preset?.base_url ?? "", model: preset?.models[0] ?? "", models: preset?.models ?? [] });
    setDiscoveryError("");
    setNotice(null);
  };

  const openEdit = (profile: Profile) => {
    setDraft({ id: profile.id, name: profile.name, provider: profile.provider, protocol: profile.protocol,
      base_url: profile.base_url, model: profile.model, api_key: "", models: profile.models,
      has_api_key: profile.has_api_key, api_key_unavailable: profile.api_key_unavailable, models_discovered: false });
    setDiscoveryError("");
    setNotice(null);
  };

  const discoverModels = async () => {
    if (!draft || discoveryInFlight.current) return;
    if (!draft.base_url.trim()) {
      setDiscoveryError("请先填写 API Base URL。");
      return;
    }
    if (!draft.api_key.trim() && !draft.has_api_key) {
      setDiscoveryError("请先填写 API Key，再获取模型列表。");
      return;
    }
    discoveryInFlight.current = true;
    setDiscoveringModels(true);
    setDiscoveryError("");
    try {
      const result = await request<{ models: string[] }>("/models/discover", {
        method: "POST",
        body: JSON.stringify({
          profile_id: draft.id,
          provider: draft.provider,
          protocol: draft.protocol,
          base_url: draft.base_url,
          api_key: draft.api_key || undefined,
        }),
      });
      if (!Array.isArray(result.models) || !result.models.length) throw new Error("服务没有返回可选模型。");
      setDraft((current) => current ? {
        ...current,
        models: result.models,
        model: result.models.includes(current.model) ? current.model : result.models[0],
        models_discovered: true,
      } : current);
    } catch (error) {
      setDiscoveryError(error instanceof Error ? error.message : String(error));
    } finally {
      discoveryInFlight.current = false;
      setDiscoveringModels(false);
    }
  };

  const save = async () => {
    if (!draft) return;
    setBusy(true); setNotice(null);
    try {
      const payload = {
        id: draft.id, name: draft.name, provider: draft.provider, protocol: draft.protocol,
        base_url: draft.base_url, model: draft.model, models: draft.models,
        api_key: draft.api_key || undefined,
      };
      await request(draft.id ? `/models/profiles/${encodeURIComponent(draft.id)}` : "/models/profiles", {
        method: draft.id ? "PUT" : "POST", body: JSON.stringify(payload),
      });
      setDraft(null);
      await refresh();
      setNotice({ kind: "ok", text: "模型配置已保存。密钥不会从服务端返回。" });
    } catch (error) { setNotice({ kind: "error", text: error instanceof Error ? error.message : String(error) }); }
    finally { setBusy(false); }
  };

  const activate = async (id: string) => {
    setBusy(true); setNotice(null);
    try {
      await request(`/models/profiles/${encodeURIComponent(id)}/activate`, { method: "POST", body: "{}" });
      await refresh();
      setNotice({ kind: "ok", text: "默认模型已切换，后续对话会使用该配置。" });
    } catch (error) { setNotice({ kind: "error", text: error instanceof Error ? error.message : String(error) }); }
    finally { setBusy(false); }
  };

  const test = async (profile: Profile) => {
    setTestingId(profile.id); setNotice(null);
    try {
      const result = await request<{ latency_ms: number; provider?: string; model?: string }>(`/models/profiles/${encodeURIComponent(profile.id)}/test`, { method: "POST", body: "{}" });
      setNotice({ kind: "ok", text: `连接成功 · ${result.provider ?? profile.provider_label} / ${result.model ?? profile.model} · ${result.latency_ms} ms` });
    } catch (error) { setNotice({ kind: "error", text: error instanceof Error ? error.message : String(error) }); }
    finally { setTestingId(null); }
  };

  const remove = async (profile: Profile) => {
    if (!window.confirm(`删除模型配置「${profile.name}」？`)) return;
    setBusy(true); setNotice(null);
    try {
      await request(`/models/profiles/${encodeURIComponent(profile.id)}`, { method: "DELETE" });
      await refresh();
      setNotice({ kind: "ok", text: "配置已删除。" });
    } catch (error) { setNotice({ kind: "error", text: error instanceof Error ? error.message : String(error) }); }
    finally { setBusy(false); }
  };

  if (!catalog) return (
    <div className="settings-section">
      {loadingCatalog ? <div className="state-empty" role="status">正在读取模型配置…</div> : (
        <div className="settings-load-error" role="alert">
          <p>模型配置读取失败：{catalogError || notice?.text || "请检查 LifeOS 后端后重试。"}</p>
          <button className="ghost compact" onClick={() => { void refresh().catch(() => undefined); }}>重新加载</button>
        </div>
      )}
    </div>
  );

  const editingPreset = catalog.presets.find((item) => item.id === draft?.provider);
  return (
    <div className="settings-section">
      <div className="settings-section-heading model-settings-heading">
        <div><span className="card-kicker">MODEL PROVIDERS</span><h2>模型与 API</h2><p>添加你常用的模型服务，并设置 LifeOS 对话默认使用的模型。</p></div>
        <button className="green-button" onClick={openNew}>添加 Provider <span>＋</span></button>
      </div>

      {notice ? <div className={`settings-notice ${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>{notice.text}</div> : null}

      <div className="provider-list">
        {catalog.profiles.map((profile) => {
          const active = profile.id === catalog.active_profile_id;
          return (
            <article className={`provider-card ${active ? "is-active" : ""}`} key={profile.id}>
              <div className="provider-card-main">
                <div className="provider-avatar">{profile.provider_label.slice(0, 1)}</div>
                <div className="provider-card-copy">
                  <div className="provider-title-row"><h3>{profile.name}</h3>{active ? <span className="provider-active-badge">当前使用</span> : null}</div>
                  <p>{profile.provider_label} <span>·</span> {profile.model}</p>
                  <small>{profile.protocol === "mock" ? "本地演示，无需 API Key" : `${profile.base_url}${profile.api_key_unavailable ? " · 已保存的密钥无法读取，请重新输入" : profile.has_api_key ? ` · 密钥已设置 ${profile.api_key_hint}` : " · 未设置密钥"}`}</small>
                </div>
              </div>
              <div className="provider-actions">
                <button className="ghost compact" onClick={() => void test(profile)} disabled={busy || testingId === profile.id}>{testingId === profile.id ? "测试中…" : "测试连接"}</button>
                {!active ? <button className="ghost compact" onClick={() => void activate(profile.id)} disabled={busy}>设为默认</button> : null}
                <button className="ghost compact" onClick={() => openEdit(profile)}>编辑</button>
                {!profile.builtin ? <button className="provider-delete" onClick={() => void remove(profile)} disabled={busy}>删除</button> : null}
              </div>
            </article>
          );
        })}
      </div>

      <div className="provider-security-note"><strong>密钥与隐私</strong><p>API Key 只发送到本机 LifeOS 后端并保存在本地配置中；页面只显示是否已配置和脱敏提示。切换默认模型后，后续对话会走该 Provider。</p></div>

      {draft ? (
        <div className="settings-modal-scrim" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) setDraft(null); }}>
          <section className="provider-editor" role="dialog" aria-modal="true" aria-labelledby="provider-editor-title">
            <div className="provider-editor-heading"><div><span className="card-kicker">CONNECTION</span><h2 id="provider-editor-title">{draft.id ? "编辑模型配置" : "添加模型配置"}</h2><p>凭据留在本机，不会发送给 LifeOS 的聊天记录或 Memory。</p></div><button className="icon-close" aria-label="关闭" onClick={() => setDraft(null)}>×</button></div>
            <label>服务商<select value={draft.provider} onChange={(event) => applyPreset(event.target.value)}>{catalog.presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.label}</option>)}</select></label>
            <label>配置名称<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder={editingPreset?.label ?? "我的模型"} /></label>
            <div className="provider-form-grid">
              <label>接口协议<select value={draft.protocol} onChange={(event) => setDraft({ ...draft, protocol: event.target.value as Protocol })}><option value="openai">OpenAI 兼容</option><option value="anthropic">Anthropic</option><option value="mock">LifeOS 本地演示</option></select></label>
              <label>模型名称<input value={draft.model} onChange={(event) => setDraft({ ...draft, model: event.target.value })} placeholder="例如 gpt-4o-mini" /></label>
            </div>
            {draft.protocol !== "mock" ? <label>API Base URL<input value={draft.base_url} onChange={(event) => setDraft({ ...draft, base_url: event.target.value, models: [], model: "", models_discovered: false })} onBlur={() => { if (draft.api_key.trim() || draft.has_api_key) void discoverModels(); }} placeholder="https://api.example.com/v1" autoComplete="url" /></label> : null}
            {draft.api_key_unavailable ? <p className="provider-model-error" role="alert">已保存的密钥无法在当前 Windows 账户下解密；原加密数据已保留。请重新输入 API Key，再拉取模型列表。</p> : null}
            {draft.protocol !== "mock" ? <label>API Key<input type="password" value={draft.api_key} onChange={(event) => setDraft({ ...draft, api_key: event.target.value })} onBlur={() => { if (draft.base_url.trim()) void discoverModels(); }} placeholder={draft.api_key_unavailable ? "请重新输入 API Key" : draft.id ? "留空则保留当前密钥" : "粘贴 API Key"} autoComplete="new-password" /></label> : null}
            {draft.protocol !== "mock" ? (
              <div className="provider-model-discovery">
                <div className="provider-model-discovery-copy">
                  <strong>从服务商读取可用模型</strong>
                  <span>只请求模型目录接口，不会发送对话或消耗生成额度。</span>
                </div>
                <button type="button" className="ghost compact" onClick={() => void discoverModels()}
                  disabled={discoveringModels || busy || (!draft.api_key && !draft.has_api_key)}>
                  {discoveringModels ? "正在读取…" : draft.models_discovered ? "刷新模型列表" : "拉取模型列表"}
                </button>
                {draft.models.length ? (
                  <label className="provider-model-choice">选择模型
                    <select aria-label="选择模型" value={draft.model} onChange={(event) => setDraft({ ...draft, model: event.target.value })}>
                      {draft.models.map((model) => <option key={model} value={model}>{model}</option>)}
                    </select>
                    {!draft.models_discovered ? <small>当前是已保存/预设列表；拉取后会更新为服务商实时返回的列表。</small> : null}
                  </label>
                ) : null}
                {discoveryError ? <p className="provider-model-error" role="alert">{discoveryError}</p> : null}
                <details className="provider-model-manual">
                  <summary>模型列表不可用？手动填写模型 ID</summary>
                  <input aria-label="手动填写模型 ID" value={draft.model} onChange={(event) => setDraft({ ...draft, model: event.target.value })}
                    placeholder="例如：provider/model-name" />
                </details>
              </div>
            ) : null}
            <div className="provider-editor-footer"><span>{draft.id ? "留空 API Key 不会覆盖已保存密钥。" : "保存后可测试连接，再设为默认模型。"}</span><button className="green-button" onClick={() => void save()} disabled={busy || discoveringModels || (draft.protocol !== "mock" && !draft.model.trim())}>{busy ? "保存中…" : "保存配置"}</button></div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
