/**
 * static/js/app.js — Shared JavaScript utilities
 *
 * Loaded by base.html for every page. Provides category colour helpers
 * used by summary charts, expense tables, and category badges.
 */

const CAT_COLORS = {
  "Food & Groceries":  { bg: "#10b981", light: "#d1fae5", icon: "🛒" },
  "Outside Food":      { bg: "#f97316", light: "#ffedd5", icon: "🍽️" },
  "Transport":         { bg: "#3b82f6", light: "#dbeafe", icon: "🚗" },
  "Shopping":          { bg: "#8b5cf6", light: "#ede9fe", icon: "🛍️" },
  "Bills & Utilities": { bg: "#ef4444", light: "#fee2e2", icon: "💡" },
  "Entertainment":     { bg: "#ec4899", light: "#fce7f3", icon: "🎬" },
  "Personal Care":     { bg: "#f59e0b", light: "#fef3c7", icon: "💆" },
  "Healthcare":        { bg: "#06b6d4", light: "#cffafe", icon: "🏥" },
  "Education":         { bg: "#6366f1", light: "#e0e7ff", icon: "📚" },
  "Other":             { bg: "#64748b", light: "#f1f5f9", icon: "📦" },
};

function getCatColor(cat)  { return (CAT_COLORS[cat] || CAT_COLORS["Other"]).bg; }
function getCatLight(cat)  { return (CAT_COLORS[cat] || CAT_COLORS["Other"]).light; }
function getCatIcon(cat)   { return (CAT_COLORS[cat] || CAT_COLORS["Other"]).icon; }
