// helpers.js — Shared utilities for dashboard sub-modules

// Resolve CSS variables for Chart.js (doesn't understand var() strings)
export function getCSSVar(name) {
  return getComputedStyle(document.body).getPropertyValue(name).trim();
}

export const COLORS = {
  green: getCSSVar('--green') || '#a6e3a1',
  blue: getCSSVar('--blue') || '#89b4fa',
  pink: getCSSVar('--red') || '#f38ba8',
  peach: getCSSVar('--peach') || '#fab387',
  mauve: getCSSVar('--accent') || '#cba6f7',
  teal: '#89dceb',
  yellow: getCSSVar('--yellow') || '#f9e2af',
  text: getCSSVar('--text') || '#cdd6f4',
  surface: getCSSVar('--bg-elevated') || '#45475a'
};

// Chart.js defaults
if (typeof Chart !== 'undefined') {
  Chart.defaults.color = getCSSVar('--text-sub') || '#a6adc8';
  Chart.defaults.borderColor = getCSSVar('--bg-elevated') || '#45475a';
}
