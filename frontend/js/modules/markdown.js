// ==================== MARKDOWN RENDERER (seguro) ====================
// Mini-parser de Markdown → HTML para respostas do AI Tutor.
// Escapa HTML primeiro (previne XSS) e depois aplica formatação segura.
// Suporta: headings, bold, italic, code inline, code block, listas
// (ordenadas/não), blockquote, links, hr e parágrafos.

function _escape(text) {
  const d = document.createElement('div');
  d.textContent = text;
  return d.innerHTML;
}

/**
 * Converte markdown em HTML seguro.
 * @param {string} md - texto markdown
 * @returns {string} HTML pronto para innerHTML
 */
export function renderMarkdown(md) {
  if (!md) return '';

  // 1) Escapar TODO o HTML de entrada (segurança)
  let text = _escape(String(md));

  // 2) Code blocks ``` ``` (antes de tudo, preserva conteúdo)
  const codeBlocks = [];
  text = text.replace(/```(\w+)?\n?([\s\S]*?)```/g, (_, lang, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push(`<pre class="md-pre"><code>${code.replace(/\n$/, '')}</code></pre>`);
    return `\u0000CB${idx}\u0000`;
  });

  // 3) Code inline `x` (protege antes de outras regras)
  const inlineCodes = [];
  text = text.replace(/`([^`\n]+)`/g, (_, code) => {
    const idx = inlineCodes.length;
    inlineCodes.push(`<code class="md-code">${code}</code>`);
    return `\u0000IC${idx}\u0000`;
  });

  // 4) Processar por linhas (listas, headings, blockquote, hr)
  const lines = text.split('\n');
  const out = [];
  let listType = null; // 'ul' | 'ol'

  const closeList = () => { if (listType) { out.push(`</${listType}>`); listType = null; } };

  for (let raw of lines) {
    const line = raw;

    // Horizontal rule
    if (/^\s*(---|\*\*\*|___)\s*$/.test(line)) { closeList(); out.push('<hr class="md-hr">'); continue; }

    // Headings
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      closeList();
      const level = h[1].length;
      out.push(`<h${level} class="md-h${level}">${h[2]}</h${level}>`);
      continue;
    }

    // Blockquote
    const bq = line.match(/^>\s?(.*)$/);
    if (bq) { closeList(); out.push(`<blockquote class="md-quote">${bq[1]}</blockquote>`); continue; }

    // Lista ordenada
    const ol = line.match(/^\s*\d+\.\s+(.*)$/);
    if (ol) {
      if (listType !== 'ol') { closeList(); out.push('<ol class="md-ol">'); listType = 'ol'; }
      out.push(`<li>${ol[1]}</li>`);
      continue;
    }

    // Lista não-ordenada
    const ul = line.match(/^\s*[-*+]\s+(.*)$/);
    if (ul) {
      if (listType !== 'ul') { closeList(); out.push('<ul class="md-ul">'); listType = 'ul'; }
      out.push(`<li>${ul[1]}</li>`);
      continue;
    }

    // Linha em branco → separa parágrafos
    if (line.trim() === '') { closeList(); out.push(''); continue; }

    // Linha normal
    closeList();
    out.push(`<p class="md-p">${line}</p>`);
  }
  closeList();
  text = out.join('\n');

  // 5) Inline: negrito, itálico, links (aplicados após estrutura)
  // Negrito **x** ou __x__
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/__([^_]+)__/g, '<strong>$1</strong>');
  // Itálico *x* ou _x_ (evita conflito com bold já processado)
  text = text.replace(/(^|[^*])\*([^*\n]+)\*([^*]|$)/g, '$1<em>$2</em>$3');
  text = text.replace(/(^|[^_])_([^_\n]+)_([^_]|$)/g, '$1<em>$2</em>$3');
  // Links [texto](url) — só http(s) e caminhos internos
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+|\/[^\s)]*)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

  // 6) Restaurar code inline e blocks
  text = text.replace(/\u0000IC(\d+)\u0000/g, (_, i) => inlineCodes[+i]);
  text = text.replace(/\u0000CB(\d+)\u0000/g, (_, i) => codeBlocks[+i]);

  // Colapsar múltiplas linhas em branco
  text = text.replace(/\n{2,}/g, '\n');

  return text;
}

window.renderMarkdown = renderMarkdown;
