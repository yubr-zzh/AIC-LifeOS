import React, { useState } from "react";
import { IconCopy } from "./Icons";

export function CopyTextButton({ text, className = "", label = "复制" }: { text: string; className?: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const area = document.createElement("textarea");
        area.value = text;
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.select();
        const ok = document.execCommand?.("copy");
        area.remove();
        if (!ok) throw new Error("copy unavailable");
      }
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  };

  return (
    <button type="button" className={`copy-text-button ${className}`.trim()} onClick={(event) => void copy(event)}
      title={copied ? "已复制" : label} aria-label={copied ? "已复制" : label}>
      <IconCopy size={12} />
      <span>{copied ? "已复制" : label}</span>
    </button>
  );
}
