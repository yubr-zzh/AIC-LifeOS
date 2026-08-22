import React from "react";

interface Props {
  source: "backend" | "preview";
  label?: string;
}

export function SourceBadge({ source, label }: Props) {
  const text = label ?? (source === "backend" ? "live" : "local preview");
  return <span className={`source-badge ${source}`}>{text}</span>;
}
