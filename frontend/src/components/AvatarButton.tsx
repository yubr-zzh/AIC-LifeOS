import React, { useEffect, useRef, useState } from "react";

const AVATAR_KEY = "lifeos.avatar.v1";

interface AvatarState {
  type: "initial" | "text" | "image";
  text: string;
  image: string | null;
}

const DEFAULT_STATE: AvatarState = { type: "initial", text: "Z", image: null };

function readAvatar(): AvatarState {
  if (typeof localStorage === "undefined") return DEFAULT_STATE;
  try {
    const raw = localStorage.getItem(AVATAR_KEY);
    if (!raw) return DEFAULT_STATE;
    const parsed = JSON.parse(raw) as Partial<AvatarState>;
    return {
      type: parsed.type === "text" || parsed.type === "image" ? parsed.type : "initial",
      text: typeof parsed.text === "string" ? parsed.text : DEFAULT_STATE.text,
      image: typeof parsed.image === "string" ? parsed.image : null,
    };
  } catch {
    return DEFAULT_STATE;
  }
}

function writeAvatar(next: AvatarState) {
  if (typeof localStorage === "undefined") return;
  try { localStorage.setItem(AVATAR_KEY, JSON.stringify(next)); } catch { /* best effort */ }
}

export function AvatarButton() {
  const [state, setState] = useState<AvatarState>(() => readAvatar());
  const [open, setOpen] = useState(false);
  const [draftText, setDraftText] = useState("");
  const rootRef = useRef<HTMLDivElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  // 点外面收起 popover
  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (event: MouseEvent) => {
      if (!rootRef.current) return;
      if (event.target instanceof Node && !rootRef.current.contains(event.target)) setOpen(false);
    };
    const onEsc = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  const openPopover = () => {
    setDraftText(state.type === "text" ? state.text : "");
    setOpen(true);
  };

  const commitText = () => {
    const trimmed = draftText.trim().slice(0, 2);
    if (!trimmed) return;
    const next: AvatarState = { type: "text", text: trimmed, image: null };
    setState(next);
    writeAvatar(next);
    setOpen(false);
  };

  const onFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = typeof reader.result === "string" ? reader.result : null;
      if (!dataUrl) return;
      const next: AvatarState = { type: "image", text: state.text, image: dataUrl };
      setState(next);
      writeAvatar(next);
      setOpen(false);
    };
    reader.readAsDataURL(file);
  };

  const resetDefault = () => {
    setState(DEFAULT_STATE);
    writeAvatar(DEFAULT_STATE);
    setOpen(false);
  };

  return (
    <div className="avatar-wrap" ref={rootRef}>
      <button
        type="button"
        className={`avatar avatar-${state.type}`}
        onClick={openPopover}
        title="修改头像"
        aria-label="修改头像"
        aria-expanded={open}
        aria-haspopup="dialog"
      >
        {state.type === "image" && state.image ? (
          <img src={state.image} alt="" />
        ) : (
          <span>{state.type === "initial" ? DEFAULT_STATE.text : state.text}</span>
        )}
      </button>
      {open ? (
        <div className="avatar-popover" role="dialog" aria-label="修改头像">
          <div className="avatar-popover-head">
            <strong>修改头像</strong>
            <span className="muted small">改完即生效，仅保存在本浏览器。</span>
          </div>
          <label className="avatar-popover-row">
            <span>显示字符</span>
            <input
              type="text"
              maxLength={2}
              value={draftText}
              placeholder="1-2 字"
              onChange={(event) => setDraftText(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); commitText(); } }}
            />
            <button type="button" className="ghost sm" onClick={commitText} disabled={!draftText.trim()}>
              保存字符
            </button>
          </label>
          <label className="avatar-popover-row">
            <span>上传图片</span>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              onChange={onFileChange}
              style={{ display: "none" }}
            />
            <button type="button" className="ghost sm" onClick={() => fileRef.current?.click()}>
              选择文件
            </button>
            <span className="muted small">PNG / JPG / SVG</span>
          </label>
          <button type="button" className="avatar-reset" onClick={resetDefault}>
            恢复默认
          </button>
        </div>
      ) : null}
    </div>
  );
}