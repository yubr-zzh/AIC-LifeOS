import React from "react";
import { SourceBadge } from "./SourceBadge";

interface Props {
  title: string;
  subtitle?: string;
  source?: "backend" | "preview" | null;
  actions?: React.ReactNode;
  children: React.ReactNode;
  dense?: boolean;
  className?: string;
}

export function Panel({ title, subtitle, source, actions, children, dense, className }: Props) {
  return (
    <section className={`panel ${className ?? ""}`}>
      <header className="panel-header">
        <div className="col" style={{ gap: 2 }}>
          <span className="panel-title">{title}</span>
          {subtitle ? <span className="panel-subtitle">{subtitle}</span> : null}
        </div>
        <div className="panel-actions">
          {source ? <SourceBadge source={source} /> : null}
          {actions}
        </div>
      </header>
      <div className={`panel-body ${dense ? "dense" : ""}`}>{children}</div>
    </section>
  );
}
