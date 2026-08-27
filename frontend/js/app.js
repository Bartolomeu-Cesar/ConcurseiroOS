// ==================== ConcurseiroOS — App Orchestrator ====================
// Importa todos os módulos e registra funções globais para onclick inline

import { initOfflineListeners, escapeHtml, confirmModal, toast, removeToast, showLoading, showSpinner, showEmpty, api, undoableDelete, debounce, formatHours } from './modules/utils.js';
import { switchTab, initTabs } from './modules/tabs.js';
import { initShortcuts, goToEditalItem } from './modules/shortcuts.js';
import { load, exportProgress, importProgress, uploadPdf, initPdfs } from './modules/pdfs.js';
import { loadEdital, toggleTree, toggleAllEdital, selectEditalTopic, toggleEditalStatus, deleteEditalItem, addEdital, importEditalPdf, arquivarCargo, excluirCargo, arquivarConcurso, excluirConcurso, editarEdital, salvarEdicaoEdital, showArquivados, iniciarQuestoesPosEstudo, iniciarFlashPosEstudo, showSpacingDetails, loadKnowledgeGraph, showKgSuggestions, acceptKgSuggestion, showKgNodeInfo, initEdital } from './modules/edital.js';
import { loadCiclo, cicloTimerToggle, cicloTimerStop, importarCicloDoEdital, addCiclo, deleteCiclo, resetarCiclo, limparCiclo, switchCicloView, initCiclo } from './modules/ciclo.js';
import { loadFlashcardsToday, revealAnswer, reviewFlashcard, addFlashcard, loadAllFlashcards, toggleFlashGroup, iniciarSessaoFlash, sessaoNext, deleteFlashcard, openFlashEditModal, closeFlashEditModal, saveFlashEdit, initFlashcards, toggleGenerationMode, setFlashConfidence, startBossBattle, bossBattleReview, startAudioMode, stopAudioMode, pauseAudioMode, skipAudioCard } from './modules/flashcards.js';
import { loadSumulasToday, revealSumula, reviewSumula, addSumula, loadAllSumulas, iniciarSessaoSumulas, deleteSumula, editSumula, toggleSumulaGroup, initSumulas } from './modules/sumulas.js';
import { carregarQuestoesDia, showQuestaoDia, responderQuestaoDia, advanceQuestao, submitSelfExplanation, selectErrorChip, initQuestoes } from './modules/questoes.js';
import { loadMetas, salvarMetas, getConfigSessoes, salvarConfigSessoes, loadConfigSessoes, loadStreakBadge, initMetas } from './modules/metas.js';
import { openSelectModal, selectModalChoice, closeSelectModal, initModalSelecao } from './modules/modal-selecao.js';
import { linkPdfToTopic, linkPdfToMateria, unlinkPdf, linkPdfToDisc, openNoteModal, closeNoteModal, saveNote, deleteNote, initVincularPdf } from './modules/vincular-pdf.js';
import { toggleTheme, enterFocusMode, exitFocusMode, launchConfetti, dismissOnboarding, trapFocus, initUI } from './modules/ui.js';
import { exportarEdital, exportarCiclo, exportarFlashcards, importarEditalFile, importarCicloFile, importarFlashcardsFile } from './modules/export-import.js';
import { handleAuthNav, logout, isLoggedIn, getToken, getUser, getUserPlan, showUpgradeModal, doUpgrade, checkPlanLimit, showEditProfileModal, saveProfile, initAuth } from './modules/auth.js';

// ==================== REGISTRAR FUNÇÕES GLOBAIS ====================
// (necessário para onclick inline no HTML)
Object.assign(window, {
  // Utils
  escapeHtml, confirmModal, toast, removeToast, showLoading, showSpinner, showEmpty, api, undoableDelete,
  // Tabs
  switchTab,
  // Shortcuts
  goToEditalItem,
  // PDFs
  load, exportProgress, importProgress, uploadPdf,
  // Edital
  loadEdital, toggleTree, toggleAllEdital, selectEditalTopic, toggleEditalStatus,
  deleteEditalItem, addEdital, importEditalPdf,
  arquivarCargo, excluirCargo, arquivarConcurso, excluirConcurso,
  editarEdital, salvarEdicaoEdital, showArquivados,
  iniciarQuestoesPosEstudo, iniciarFlashPosEstudo, showSpacingDetails,
  loadKnowledgeGraph, showKgSuggestions, acceptKgSuggestion, showKgNodeInfo,
  // Ciclo
  loadCiclo, cicloTimerToggle, cicloTimerStop, importarCicloDoEdital, addCiclo, deleteCiclo, resetarCiclo, limparCiclo, switchCicloView,
  // Flashcards
  loadFlashcardsToday, revealAnswer, reviewFlashcard, addFlashcard, loadAllFlashcards,
  toggleFlashGroup, iniciarSessaoFlash, sessaoNext, deleteFlashcard,
  openFlashEditModal, closeFlashEditModal, saveFlashEdit,
  toggleGenerationMode, setFlashConfidence, startBossBattle, bossBattleReview,
  startAudioMode, stopAudioMode, pauseAudioMode, skipAudioCard,
  // Súmulas
  loadSumulasToday, revealSumula, reviewSumula, addSumula, loadAllSumulas,
  iniciarSessaoSumulas, deleteSumula, editSumula, toggleSumulaGroup,
  // Questões
  carregarQuestoesDia, showQuestaoDia, responderQuestaoDia, advanceQuestao, submitSelfExplanation, selectErrorChip,
  // Metas
  loadMetas, salvarMetas, getConfigSessoes, salvarConfigSessoes, loadConfigSessoes, loadStreakBadge,
  // Modal Seleção
  openSelectModal, selectModalChoice, closeSelectModal,
  // Vincular PDF + Notas
  linkPdfToTopic, linkPdfToMateria, unlinkPdf, linkPdfToDisc, openNoteModal, closeNoteModal, saveNote, deleteNote,
  // UI
  toggleTheme, enterFocusMode, exitFocusMode, launchConfetti, dismissOnboarding, trapFocus,
  // Export/Import
  exportarEdital, exportarCiclo, exportarFlashcards, importarEditalFile, importarCicloFile, importarFlashcardsFile,
  // Auth
  handleAuthNav, logout, isLoggedIn, getToken, getUser, getUserPlan, showUpgradeModal, doUpgrade, checkPlanLimit, showEditProfileModal, saveProfile,
});

// Referências internas para módulo export-import
window._loadEdital = loadEdital;
window._loadCiclo = loadCiclo;
window._loadAllFlashcards = loadAllFlashcards;
window._loadFlashcardsToday = loadFlashcardsToday;

// ==================== INICIALIZAÇÃO ====================
initOfflineListeners();
initModalSelecao();
initMetas();
initAuth();

initVincularPdf({ load, loadEdital });
initPdfs({ linkPdfToDisc, unlinkPdf });
initEdital({ loadMetas, loadStreakBadge, getConfigSessoes, linkPdfToTopic, linkPdfToMateria, openNoteModal });
initCiclo({ loadStreakBadge });
initFlashcards({ loadMetas, loadStreakBadge, getConfigSessoes });
initSumulas();
initQuestoes({ loadMetas, loadStreakBadge, getConfigSessoes });
initTabs({ carregarQuestoesDia, iniciarSessaoFlash });
initShortcuts();
initUI();
