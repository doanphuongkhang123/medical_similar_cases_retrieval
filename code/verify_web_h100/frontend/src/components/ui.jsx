import React from "react";
import { Clock, CheckCircle2, FlagTriangleRight } from "lucide-react";
import { C } from "../theme.js";

export function StatusBadge({ score, legacyStatus }) {
  const s = Number.isInteger(score) && score >= 1 && score <= 5
    ? { label: `Đã chấm ${score}/5`, bg: C.tealSoft, fg: "#0B6C62", icon: CheckCircle2 }
    : legacyStatus && legacyStatus !== "pending"
      ? { label: "Cần chấm lại", bg: C.amberSoft, fg: "#8A6413", icon: FlagTriangleRight }
      : { label: "Chưa đánh giá", bg: "#EDF0F1", fg: C.inkFaint, icon: Clock };
  const Icon = s.icon;
  return (
    <span
      style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        background: s.bg, color: s.fg, fontSize: 11, fontWeight: 600,
        padding: "3px 8px", borderRadius: 20, fontFamily: "'Inter', sans-serif",
        letterSpacing: 0.2,
      }}
    >
      <Icon size={11} strokeWidth={2.4} />
      {s.label}
    </span>
  );
}

export function UrgencyDot({ urgency }) {
  const color = urgency > 70 ? C.red : urgency > 45 ? C.amber : C.teal;
  return <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%", background: color, flexShrink: 0 }} />;
}

export function InfoCard({ title, children }) {
  return (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: "14px 16px" }}>
      <div style={{ fontSize: 10.5, fontWeight: 700, color: C.inkFaint, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>
        {title}
      </div>
      {children}
    </div>
  );
}

export function ActionButton({ label, icon: Icon, color, onClick, active, filled, disabled }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        display: "flex", alignItems: "center", gap: 6, padding: "9px 14px", borderRadius: 7,
        fontSize: 13, fontWeight: 600, cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.6 : 1,
        border: `1.5px solid ${color}`,
        background: active || filled ? color : "transparent",
        color: active || filled ? "#fff" : color,
        transition: "all 0.12s ease",
      }}
    >
      <Icon size={14} /> {label}
    </button>
  );
}

export const thStyle = { textAlign: "left", padding: "9px 14px", fontSize: 11, fontWeight: 700, color: "#5B6570", textTransform: "uppercase", letterSpacing: 0.4 };
export const tdStyle = { padding: "9px 14px" };
