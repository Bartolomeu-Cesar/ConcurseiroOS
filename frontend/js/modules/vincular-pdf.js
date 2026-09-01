// ==================== VINCULAR PDF + NOTAS POR TÓPICO ====================
import { state } from './state.js';
import { toast, escapeHtml, confirmModal } from './utils.js';
import { openSelectModal } from './modal-selecao.js';

let _loadFn = null;
let _loadEditalFn = null;

export async function linkPdfToTopic(id, materia) {
  const tree = await fetch('/api/tree').then(r => r.json());
  const pdfs = [];
  function extractPdfs(nodes, prefix) {
    for (const n of nodes) {
      if (n.type === 'pdf') pdfs.push(prefix ? `${prefix}/${n.name}` : n.name);
      else if (n.type === 'folder') extractPdfs(n.children, prefix ? `${prefix}/${n.name}` : n.name);
    }
  }
  extractPdfs(tree, '');
  if (pdfs.length === 0) {
    toast('Nenhum PDF disponível. Adicione PDFs na pasta backend/pdfs/', 'warning');
    return;
  }
  openSelectModal(`📖 Vincular PDF a "${materia}"`, pdfs.map(p => ({
    icon: '📄',
    label: p.split('/').pop().replace(/_/g, ' ').replace('.pdf', ''),
    sub: p.includes('/') ? p.split('/').slice(0, -1).join('/') : '',
    value: p
  })), async (choice) => {
    const pdfPath = choice.value;
    await fetch(`/api/edital/${id}/pdf`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pdf_link: pdfPath, pdf_pagina: 1 })
    });
    if (_loadEditalFn) _loadEditalFn();
  });
}

export async function linkPdfToMateria(materia, editalNome, cargo) {
  const tree = await fetch('/api/tree').then(r => r.json());
  const pdfs = [];
  function extractPdfs(nodes, prefix) {
    for (const n of nodes) {
      if (n.type === 'pdf') pdfs.push(prefix ? `${prefix}/${n.name}` : n.name);
      else if (n.type === 'folder') extractPdfs(n.children, prefix ? `${prefix}/${n.name}` : n.name);
    }
  }
  extractPdfs(tree, '');
  if (pdfs.length === 0) { toast('Nenhum PDF disponível.', 'warning'); return; }
  openSelectModal(`🔗 Vincular PDF a "${materia}"`, pdfs.map(p => ({
    icon: '📄',
    label: p.split('/').pop().replace(/_/g, ' ').replace('.pdf', ''),
    sub: p.includes('/') ? p.split('/').slice(0, -1).join('/') : '',
    value: p
  })), async (choice) => {
    await fetch(`/api/edital/vincular-bulk?materia=${encodeURIComponent(materia)}&pdf_link=${encodeURIComponent(choice.value)}&edital_nome=${encodeURIComponent(editalNome || '')}&cargo=${encodeURIComponent(cargo || '')}`, { method: 'PUT' });
    if (_loadEditalFn) _loadEditalFn();
  });
}

export async function unlinkPdf(pdfPath) {
  const vinculado = state.editalData.find(e => e.pdf_link === pdfPath);
  const ok = await confirmModal('Desvincular PDF', `Desvincular <strong>"${pdfPath.split('/').pop()}"</strong> de <strong>"${vinculado?.materia || 'disciplina'}"</strong>?`, { confirmText: 'Desvincular', type: 'warning', icon: '❌' });
  if (!ok) return;
  await fetch(`/api/edital/desvincular-pdf?pdf_link=${encodeURIComponent(pdfPath)}`, { method: 'PUT' });
  state.editalData = await fetch('/api/edital').then(r => r.json());
  if (_loadFn) await _loadFn();
}

export async function linkPdfToDisc(pdfPath) {
  const materias = [...new Set(state.editalData.map(e => e.materia))].sort();
  if (materias.length === 0) { toast('Nenhuma disciplina cadastrada no edital.', 'warning'); return; }
  openSelectModal(`🔗 Vincular "${pdfPath.split('/').pop()}"`, materias.map(m => ({
    icon: '📚',
    label: m,
    sub: `${state.editalData.filter(e => e.materia === m).length} tópicos`,
    value: m
  })), async (choice) => {
    const materia = choice.value;
    const editaisCargos = [...new Set(state.editalData.filter(e => e.materia === materia).map(e => `${e.edital_nome}|${e.cargo}`))];
    let editalNome = '', cargo = '';
    if (editaisCargos.length > 1) {
      openSelectModal(`📋 "${materia}" existe em vários editais`, editaisCargos.map(ec => {
        const [e, c] = ec.split('|');
        return { icon: '👤', label: `${e} - ${c}`, sub: '', value: ec };
      }).concat([{ icon: '📌', label: 'Todos os editais', sub: 'Vincular em todas as ocorrências', value: '' }]), async (ch2) => {
        if (ch2.value) { [editalNome, cargo] = ch2.value.split('|'); }
        await fetch(`/api/edital/vincular-bulk?materia=${encodeURIComponent(materia)}&pdf_link=${encodeURIComponent(pdfPath)}&edital_nome=${encodeURIComponent(editalNome)}&cargo=${encodeURIComponent(cargo)}`, { method: 'PUT' });
        state.editalData = await fetch('/api/edital').then(r => r.json());
        if (_loadFn) await _loadFn();
      });
    } else {
      await fetch(`/api/edital/vincular-bulk?materia=${encodeURIComponent(materia)}&pdf_link=${encodeURIComponent(pdfPath)}`, { method: 'PUT' });
      state.editalData = await fetch('/api/edital').then(r => r.json());
      if (_loadFn) await _loadFn();
    }
  });
}

// --- Notas por tópico ---
export function openNoteModal(id) {
  state.noteCurrentId = id;
  document.getElementById('note-modal').classList.add('show');
  loadNotesForTopic(id);
}

export function closeNoteModal() {
  document.getElementById('note-modal').classList.remove('show');
  state.noteCurrentId = null;
}

async function loadNotesForTopic(id) {
  const notes = await fetch(`/api/edital/${id}/notas`).then(r => r.json());
  const list = document.getElementById('note-modal-list');
  list.innerHTML = notes.map(n => `
    <div class="nota-item">
      <span class="nota-text">${escapeHtml(n.conteudo)}</span>
      <button class="nota-del" onclick="deleteNote(${n.id})" aria-label="Excluir nota">×</button>
    </div>
  `).join('');
}

export async function saveNote() {
  const text = document.getElementById('note-modal-input').value.trim();
  if (!text) return;
  await fetch(`/api/edital/${state.noteCurrentId}/notas`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ edital_id: state.noteCurrentId, conteudo: text })
  });
  document.getElementById('note-modal-input').value = '';
  loadNotesForTopic(state.noteCurrentId);
}

export async function deleteNote(id) {
  await fetch(`/api/notas-topico/${id}`, { method: 'DELETE' });
  loadNotesForTopic(state.noteCurrentId);
}

export function initVincularPdf(deps) {
  _loadFn = deps.load;
  _loadEditalFn = deps.loadEdital;

  document.getElementById('note-modal').addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay')) closeNoteModal();
  });
}
