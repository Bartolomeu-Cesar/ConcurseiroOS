/**
 * Ilustrações SVG geométricas leves para empty states.
 *
 * Estética coesa com a marca (Catppuccin): formas simples, cores dos tokens,
 * sem dependências e sem imagens externas. Usam currentColor/variáveis quando
 * possível para funcionar em tema claro e escuro.
 *
 * Uso:
 *   import { illustration } from './modules/illustrations.js';
 *   container.innerHTML = `<div class="empty-state">
 *     ${illustration('questoes')}
 *     <p class="empty-msg">Nenhuma questão ainda</p>
 *   </div>`;
 *
 * Também exposto em window.illustration para uso inline.
 */

const _WRAP = (inner) =>
  `<svg class="empty-illustration" viewBox="0 0 120 100" width="120" height="100" role="img" aria-hidden="true" fill="none" xmlns="http://www.w3.org/2000/svg">${inner}</svg>`;

const _ILLUS = {
  // Prancheta com check — questões
  questoes: `
    <rect x="34" y="18" width="52" height="66" rx="6" fill="var(--bg-elevated,#45475a)" stroke="var(--accent,#cba6f7)" stroke-width="2"/>
    <rect x="48" y="12" width="24" height="12" rx="4" fill="var(--accent,#cba6f7)"/>
    <line x1="44" y1="38" x2="76" y2="38" stroke="var(--text-muted,#6c7086)" stroke-width="3" stroke-linecap="round"/>
    <line x1="44" y1="50" x2="70" y2="50" stroke="var(--text-muted,#6c7086)" stroke-width="3" stroke-linecap="round"/>
    <line x1="44" y1="62" x2="64" y2="62" stroke="var(--text-muted,#6c7086)" stroke-width="3" stroke-linecap="round"/>
    <circle cx="86" cy="70" r="14" fill="var(--green,#a6e3a1)"/>
    <path d="M80 70 l4 4 l8 -9" stroke="#1e1e2e" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>`,
  // Documento/página — PDFs
  pdfs: `
    <rect x="40" y="16" width="46" height="60" rx="5" fill="var(--bg-elevated,#45475a)" stroke="var(--blue,#89b4fa)" stroke-width="2"/>
    <path d="M74 16 l12 12 h-12 z" fill="var(--blue,#89b4fa)" opacity="0.5"/>
    <line x1="48" y1="40" x2="78" y2="40" stroke="var(--text-muted,#6c7086)" stroke-width="3" stroke-linecap="round"/>
    <line x1="48" y1="50" x2="78" y2="50" stroke="var(--text-muted,#6c7086)" stroke-width="3" stroke-linecap="round"/>
    <line x1="48" y1="60" x2="66" y2="60" stroke="var(--text-muted,#6c7086)" stroke-width="3" stroke-linecap="round"/>
    <circle cx="84" cy="74" r="4" fill="var(--peach,#fab387)"/>`,
  // Gráfico de barras — sem dados/analytics
  dados: `
    <line x1="30" y1="80" x2="94" y2="80" stroke="var(--text-muted,#6c7086)" stroke-width="2" stroke-linecap="round"/>
    <rect x="38" y="56" width="12" height="24" rx="3" fill="var(--blue,#89b4fa)" opacity="0.8"/>
    <rect x="56" y="44" width="12" height="36" rx="3" fill="var(--accent,#cba6f7)" opacity="0.8"/>
    <rect x="74" y="34" width="12" height="46" rx="3" fill="var(--green,#a6e3a1)" opacity="0.8"/>
    <circle cx="44" cy="48" r="3" fill="var(--blue,#89b4fa)"/>
    <circle cx="62" cy="36" r="3" fill="var(--accent,#cba6f7)"/>
    <circle cx="80" cy="26" r="3" fill="var(--green,#a6e3a1)"/>
    <path d="M44 48 L62 36 L80 26" stroke="var(--text-sub,#9399b2)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>`,
  // Troféu — tudo concluído / conquista
  concluido: `
    <path d="M46 24 h28 v10 a14 14 0 0 1 -28 0 z" fill="var(--yellow,#f9e2af)"/>
    <path d="M46 28 h-8 a8 8 0 0 0 8 10" stroke="var(--yellow,#f9e2af)" stroke-width="3" fill="none"/>
    <path d="M74 28 h8 a8 8 0 0 1 -8 10" stroke="var(--yellow,#f9e2af)" stroke-width="3" fill="none"/>
    <rect x="55" y="46" width="10" height="12" fill="var(--yellow,#f9e2af)" opacity="0.7"/>
    <rect x="46" y="58" width="28" height="8" rx="3" fill="var(--yellow,#f9e2af)"/>
    <circle cx="60" cy="31" r="4" fill="#1e1e2e" opacity="0.15"/>`,
  // Lupa — nenhum resultado de busca
  busca: `
    <circle cx="54" cy="46" r="20" fill="none" stroke="var(--accent,#cba6f7)" stroke-width="3"/>
    <line x1="68" y1="60" x2="84" y2="76" stroke="var(--accent,#cba6f7)" stroke-width="4" stroke-linecap="round"/>
    <line x1="46" y1="46" x2="62" y2="46" stroke="var(--text-muted,#6c7086)" stroke-width="2.5" stroke-linecap="round"/>`,
};

export function illustration(tipo = 'dados') {
  return _WRAP(_ILLUS[tipo] || _ILLUS.dados);
}

window.illustration = illustration;
