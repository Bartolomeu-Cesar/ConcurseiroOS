// ==================== EXPORT / IMPORT ====================
import { toast } from './utils.js';
import { getToken } from './auth.js';

/**
 * Faz download autenticado de um endpoint que exige Authorization: Bearer.
 *
 * window.open()/navegação direta NÃO envia o header Authorization, resultando
 * em 401 "Token não fornecido". Por isso buscamos via fetch (com o header) e
 * disparamos o download a partir do Blob recebido.
 */
async function downloadAutenticado(url, fallbackFilename) {
  const token = getToken();
  const headers = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(url, { headers });
  if (!res.ok) {
    if (res.status === 401) throw new Error('Sessão expirada. Faça login novamente.');
    throw new Error(`Falha ao exportar (HTTP ${res.status})`);
  }

  // Extrai o nome do arquivo do Content-Disposition, se presente.
  let filename = fallbackFilename;
  const disp = res.headers.get('Content-Disposition') || '';
  const match = disp.match(/filename="?([^"]+)"?/i);
  if (match) filename = match[1];

  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}

/**
 * Envia um arquivo (multipart) para um endpoint autenticado de importação.
 * fetch com FormData NÃO deve setar Content-Type manualmente (o browser
 * define o boundary), mas o header Authorization precisa ser incluído.
 */
async function importarArquivo(url, file) {
  const token = getToken();
  const headers = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(url, { method: 'POST', headers, body: formData });
  return res.json();
}

export async function exportarEdital(formato) {
  try {
    await downloadAutenticado(`/api/edital/exportar?formato=${formato}`, `edital.${formato}`);
  } catch (e) {
    toast(e.message || 'Erro ao exportar edital', 'error');
  }
}

export async function exportarCiclo(formato) {
  try {
    await downloadAutenticado(`/api/ciclo/exportar?formato=${formato}`, `ciclo.${formato}`);
  } catch (e) {
    toast(e.message || 'Erro ao exportar ciclo', 'error');
  }
}

export async function exportarFlashcards(formato) {
  try {
    await downloadAutenticado(`/api/flashcards/exportar?formato=${formato}`, `flashcards.${formato}`);
  } catch (e) {
    toast(e.message || 'Erro ao exportar flashcards', 'error');
  }
}

export async function importarEditalFile(input) {
  const file = input.files?.[0];
  if (!file) return;
  try {
    const data = await importarArquivo('/api/edital/importar', file);
    if (data.ok) { toast(`Importados ${data.importados} tópicos do edital!`, 'success'); window._loadEdital?.(); }
    else { toast(data.detail || 'Erro ao importar edital', 'error'); }
  } catch (e) { toast('Erro ao importar edital', 'error'); }
  input.value = '';
}

export async function importarCicloFile(input) {
  const file = input.files?.[0];
  if (!file) return;
  try {
    const data = await importarArquivo('/api/ciclo/importar', file);
    if (data.ok) { toast(`Importadas ${data.importados} matérias no ciclo!`, 'success'); window._loadCiclo?.(); }
    else { toast(data.detail || 'Erro ao importar ciclo', 'error'); }
  } catch (e) { toast('Erro ao importar ciclo', 'error'); }
  input.value = '';
}

export async function importarFlashcardsFile(input) {
  const file = input.files?.[0];
  if (!file) return;
  try {
    const data = await importarArquivo('/api/flashcards/importar', file);
    if (data.ok) {
      const dup = data.duplicados_ignorados || 0;
      const msg = dup > 0
        ? `Importados ${data.importados} flashcards (${dup} duplicado${dup > 1 ? 's' : ''} ignorado${dup > 1 ? 's' : ''})`
        : `Importados ${data.importados} flashcards!`;
      toast(msg, 'success');
      window._loadAllFlashcards?.(); window._loadFlashcardsToday?.();
    }
    else { toast(data.detail || 'Erro ao importar flashcards', 'error'); }
  } catch (e) { toast('Erro ao importar flashcards', 'error'); }
  input.value = '';
}
