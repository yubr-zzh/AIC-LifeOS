import React, { useEffect, useRef, useState } from "react";

const STORAGE_KEY = "lifeos.chat.splitRatio.v1";
const MIN_RATIO = 0.38;
const MAX_RATIO = 0.78;
const DEFAULT_RATIO = 0.68;

function clampRatio(value: number): number {
  return Math.min(MAX_RATIO, Math.max(MIN_RATIO, value));
}

function readRatio(): number {
  try {
    const saved = Number(localStorage.getItem(STORAGE_KEY));
    return Number.isFinite(saved) && saved > 0 ? clampRatio(saved) : DEFAULT_RATIO;
  } catch {
    return DEFAULT_RATIO;
  }
}

export function ResizableChatSplit({ chat, agent }: { chat: React.ReactNode; agent: React.ReactNode }) {
  const [ratio, setRatio] = useState(readRatio);
  const [dragging, setDragging] = useState(false);
  const grid = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);

  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, String(ratio)); } catch { /* best effort */ }
  }, [ratio]);

  const updateFromClientX = (clientX: number) => {
    const rect = grid.current?.getBoundingClientRect();
    if (!rect || rect.width <= 0) return;
    const usable = Math.max(1, rect.width - 10);
    setRatio(clampRatio((clientX - rect.left) / usable));
  };

  const stopDragging = (event: React.PointerEvent<HTMLDivElement>) => {
    draggingRef.current = false;
    setDragging(false);
    document.body.classList.remove("chat-split-resizing");
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      setRatio((value) => clampRatio(value - 0.02));
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      setRatio((value) => clampRatio(value + 0.02));
    } else if (event.key === "Home") {
      event.preventDefault();
      setRatio(MIN_RATIO);
    } else if (event.key === "End") {
      event.preventDefault();
      setRatio(MAX_RATIO);
    }
  };

  return (
    <div ref={grid} className={`chat-split-grid resizable ${dragging ? "dragging" : ""}`}
      style={{ gridTemplateColumns: `minmax(0, ${ratio}fr) 10px minmax(0, ${1 - ratio}fr)` }}>
      {chat}
      <div className="chat-split-resizer" role="separator" aria-orientation="vertical"
        aria-label="调整对话与 Agent 面板宽度" aria-valuemin={Math.round(MIN_RATIO * 100)}
        aria-valuemax={Math.round(MAX_RATIO * 100)} aria-valuenow={Math.round(ratio * 100)}
        tabIndex={0} title="左右拖动调整宽度，双击恢复默认"
        onPointerDown={(event) => {
          event.preventDefault();
          draggingRef.current = true;
          setDragging(true);
          document.body.classList.add("chat-split-resizing");
          event.currentTarget.setPointerCapture?.(event.pointerId);
          updateFromClientX(event.clientX);
        }}
        onPointerMove={(event) => { if (draggingRef.current) updateFromClientX(event.clientX); }}
        onPointerUp={stopDragging}
        onPointerCancel={stopDragging}
        onDoubleClick={() => setRatio(DEFAULT_RATIO)}
        onKeyDown={onKeyDown}>
        <span className="chat-split-grip" aria-hidden="true" />
      </div>
      {agent}
    </div>
  );
}