// modules/local-pdfs.js
// ==================== MODO PDF LOCAL (privacidade) ====================
// Permite estudar PDFs que ficam NA MÁQUINA do estudante — o binário nunca é
// enviado ao servidor. Usa a File System Access API (Chrome/Edge desktop) para
// o usuário escolher uma pasta uma única vez; o handle é persistido em IndexedDB
// e reutilizado nas próximas sessões (com re-permissão quando o browser exigir).
//
// O servidor só guarda o PROGRESSO (página atual/total) via /api/progress, sob
// paths com prefixo "local:" — nenhum conteúdo do PDF trafega. Recursos que
// dependem de o servidor ler o arquivo (IA: tutor/análise/questões) ficam
// indisponíveis para PDFs locais nesta fase.
//
// Contrato de path: "local:<caminho-relativo-na-pasta>" (ex: "local:Dir1/aula.pdf").

const LOCAL_PREFIX = 'local:';
const IDB_NAME = 'concurseiro_local_pdfs';
const IDB_STORE = 'handles';
const IDB_KEY = 'root_dir';

// ---------- Detecção de suporte ----------
export function suportaPdfLocal() {
  return typeof window.showDirectoryPicker === 'function';
}

export function isLocalPath(path) {
  return typeof path === 'string' && path.startsWith(LOCAL_PREFIX);
}

export function stripLocalPrefix(path) {
  return isLocalPath(path) ? path.slice(LOCAL_PREFIX.length) : path;
}

export function toLocalPath(relPath) {
  return LOCAL_PREFIX + relPath;
}

// ---------- IndexedDB (persistência do handle da pasta) ----------
function _idbOpen() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(IDB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(IDB_STORE)) db.createObjectStore(IDB_STORE);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function _idbSet(key, value) {
  const db = await _idbOpen();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_STORE, 'readwrite');
    tx.objectStore(IDB_STORE).put(value, key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function _idbGet(key) {
  const db = await _idbOpen();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_STORE, 'readonly');
    const req = tx.objectStore(IDB_STORE).get(key);
    req.onsuccess = () => resolve(req.result || null);
    req.onerror = () => reject(req.error);
  });
}

async function _idbDel(key) {
  const db = await _idbOpen();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_STORE, 'readwrite');
    tx.objectStore(IDB_STORE).delete(key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

// ---------- Permissão do handle ----------
async function _verificarPermissao(handle, comPrompt = false) {
  if (!handle) return false;
  const opts = { mode: 'read' };
  try {
    if ((await handle.queryPermission(opts)) === 'granted') return true;
    if (comPrompt && (await handle.requestPermission(opts)) === 'granted') return true;
  } catch (e) { /* alguns browsers lançam se não suportado */ }
  return false;
}

// ---------- Escolher / recuperar a pasta raiz ----------
// Abre o seletor nativo, persiste o handle e retorna-o. Só funciona em resposta
// a um gesto do usuário (clique).
export async function escolherPastaLocal() {
  if (!suportaPdfLocal()) {
    throw new Error('Seu navegador não suporta a seleção de pasta local. Use Chrome ou Edge no computador.');
  }
  const handle = await window.showDirectoryPicker({ id: 'concurseiro-pdfs', mode: 'read' });
  await _idbSet(IDB_KEY, handle);
  return handle;
}

// Recupera o handle salvo (se houver) e garante permissão. `comPrompt` só deve
// ser true dentro de um gesto do usuário.
export async function getPastaLocal(comPrompt = false) {
  const handle = await _idbGet(IDB_KEY);
  if (!handle) return null;
  const ok = await _verificarPermissao(handle, comPrompt);
  return ok ? handle : null;
}

export async function esquecerPastaLocal() {
  await _idbDel(IDB_KEY);
}

// ---------- Varredura da pasta → árvore de PDFs ----------
// Retorna uma árvore no MESMO formato de /api/pdf/organizacao:
// [{type:'folder', name, children:[...]}, {type:'pdf', name, path:'local:...'}]
export async function listarPdfsLocais(handle, _prefix = '') {
  const folders = [];
  const pdfs = [];
  for await (const [nome, entry] of handle.entries()) {
    if (entry.kind === 'directory') {
      const rel = _prefix ? `${_prefix}/${nome}` : nome;
      const children = await listarPdfsLocais(entry, rel);
      if (children.length) folders.push({ type: 'folder', name: nome, children });
    } else if (entry.kind === 'file' && nome.toLowerCase().endsWith('.pdf')) {
      const rel = _prefix ? `${_prefix}/${nome}` : nome;
      pdfs.push({ type: 'pdf', name: nome, path: toLocalPath(rel) });
    }
  }
  // Ordena: pastas antes, alfabético.
  folders.sort((a, b) => a.name.localeCompare(b.name));
  pdfs.sort((a, b) => a.name.localeCompare(b.name));
  return [...folders, ...pdfs];
}

// ---------- Obter o File binário de um path local ----------
// Navega a hierarquia a partir do handle raiz até o arquivo e retorna um File.
export async function obterArquivoLocal(handle, localPath) {
  const rel = stripLocalPrefix(localPath);
  const partes = rel.split('/').filter(Boolean);
  let dir = handle;
  for (let i = 0; i < partes.length - 1; i++) {
    dir = await dir.getDirectoryHandle(partes[i]);
  }
  const fileHandle = await dir.getFileHandle(partes[partes.length - 1]);
  return await fileHandle.getFile();
}

// Conveniência: resolve o handle salvo e retorna o File direto.
export async function obterArquivoLocalPorPath(localPath, comPrompt = false) {
  const handle = await getPastaLocal(comPrompt);
  if (!handle) throw new Error('Pasta local não configurada ou sem permissão.');
  return await obterArquivoLocal(handle, localPath);
}
