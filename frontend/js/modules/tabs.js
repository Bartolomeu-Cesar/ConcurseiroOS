// ==================== TAB NAVIGATION ====================
import { toast } from './utils.js';

export function switchTab(tabId) {
  document.querySelectorAll('.tab-btn').forEach(b => { b.classList.remove('active'); b.setAttribute('aria-selected', 'false'); });
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  const btn = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
  if (btn) {
    btn.classList.add('active');
    btn.setAttribute('aria-selected', 'true');
  }
  const tab = document.getElementById(tabId);
  if (tab) tab.classList.add('active');
}

export function initTabs(deps) {
  // deps: { carregarQuestoesDia, iniciarSessaoFlash }
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => { b.classList.remove('active'); b.setAttribute('aria-selected', 'false'); });
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      btn.classList.add('active');
      btn.setAttribute('aria-selected', 'true');
      document.getElementById(btn.dataset.tab).classList.add('active');
    });
  });

  // Abrir aba via hash na URL
  const hash = window.location.hash.replace('#', '');
  if (hash && document.getElementById(hash)) {
    switchTab(hash);
  }

  // Tratar ação pós-PDF (veio do viewer após concluir leitura)
  const posPdfAcao = localStorage.getItem('pos_pdf_acao');
  if (posPdfAcao) {
    localStorage.removeItem('pos_pdf_acao');
    switchTab('tab-flashcards');
    setTimeout(() => {
      if (posPdfAcao === 'questoes') {
        deps.carregarQuestoesDia();
        toast('📝 Questões pós-leitura!', 'success');
      } else if (posPdfAcao === 'flashcards') {
        deps.iniciarSessaoFlash('aleatorio');
        toast('🧠 Flashcards pós-leitura!', 'success');
      }
    }, 500);
  }
}
