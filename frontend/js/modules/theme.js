/**
 * Theme Toggle Module
 * 
 * Dark/light theme management extracted from multiple pages.
 * Uses Catppuccin Mocha (dark) / Latte (light) color scheme.
 * Persists choice in localStorage('theme').
 * Respects system preference via CSS @media prefers-color-scheme when no user choice.
 * 
 * Usage:
 *   import { toggleTheme, initTheme } from './modules/theme.js';
 *   initTheme();  // Call on page load to restore saved preference
 *   // Bind toggleTheme to a button: <button onclick="toggleTheme()">🌓</button>
 */

// ==================== INIT THEME ====================
/**
 * Restore saved theme on page load.
 * Call this early (ideally in <head> or at top of script).
 * If no preference is saved, relies on CSS @media prefers-color-scheme.
 */
export function initTheme() {
  const saved = localStorage.getItem('theme');
  if (saved === 'light') {
    document.body.classList.add('light-theme', 'theme-forced');
  } else if (saved === 'dark') {
    document.body.classList.add('theme-forced');
  }
  // If no saved preference, CSS @media prefers-color-scheme handles it
}

// ==================== TOGGLE THEME ====================
/**
 * Toggle between dark and light theme.
 * Updates body class, localStorage, and meta theme-color tag.
 * @returns {'light'|'dark'} The new active theme
 */
export function toggleTheme() {
  const body = document.body;
  body.classList.add('theme-forced');
  const isLight = body.classList.toggle('light-theme');
  localStorage.setItem('theme', isLight ? 'light' : 'dark');

  // Update meta theme-color for mobile browsers
  const metaTheme = document.querySelector('meta[name=theme-color]');
  if (metaTheme) {
    metaTheme.content = isLight ? '#eff1f5' : '#1e1e2e';
  }

  return isLight ? 'light' : 'dark';
}

// ==================== GET CURRENT THEME ====================
/**
 * Get the current active theme.
 * @returns {'light'|'dark'}
 */
export function getTheme() {
  return document.body.classList.contains('light-theme') ? 'light' : 'dark';
}

export default toggleTheme;
