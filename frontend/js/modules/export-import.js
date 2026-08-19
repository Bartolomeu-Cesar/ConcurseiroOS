// ==================== EXPORT / IMPORT ====================
import { toast } from './utils.js';

export function exportarEdital(formato) {
  window.open(`/api/edital/exportar?formato=${formato}`, '_blank');
}

export function exportarCiclo(formato) {
  window.open(`/api/ciclo/exportar?formato=${formato}`, '_blank');
}

export function exportarFlashcards(formato) {
  window.open(`/api/flashcards/exportar?formato=${formato}`, '_blank');
}

export async function importarEditalFile(input) {
  const file = input.files?.[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  try {
    const res = await fetch('/api/edital/importar', { method: 'POST', body: formData });
    const data = await res.json();
    if (data.ok) { toast(`Importados ${data.importados} tópicos do edital!`, 'success'); window._loadEdital?.(); }
    else { toast('Erro ao importar edital', 'error'); }
  } catch (e) { toast('Erro ao importar edital', 'error'); }
  input.value = '';
}

export async function importarCicloFile(input) {
  const file = input.files?.[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  try {
    const res = await fetch('/api/ciclo/importar', { method: 'POST', body: formData });
    const data = await res.json();
    if (data.ok) { toast(`Importadas ${data.importados} matérias no ciclo!`, 'success'); window._loadCiclo?.(); }
    else { toast('Erro ao importar ciclo', 'error'); }
  } catch (e) { toast('Erro ao importar ciclo', 'error'); }
  input.value = '';
}

export async function importarFlashcardsFile(input) {
  const file = input.files?.[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  try {
    const res = await fetch('/api/flashcards/importar', { method: 'POST', body: formData });
    const data = await res.json();
    if (data.ok) { toast(`Importados ${data.importados} flashcards!`, 'success'); window._loadAllFlashcards?.(); window._loadFlashcardsToday?.(); }
    else { toast('Erro ao importar flashcards', 'error'); }
  } catch (e) { toast('Erro ao importar flashcards', 'error'); }
  input.value = '';
}
