// ==================== API TYPES ====================

interface ToastAction {
  label: string;
  onClick: () => void;
}

interface Toast {
  message: string;
  type: 'success' | 'error' | 'warning' | 'info';
  duration?: number;
  action?: ToastAction;
}

interface Flashcard {
  id: number;
  pergunta: string;
  resposta: string;
  proxima_revisao: string;
  intervalo_dias: number;
  easiness_factor?: number;
  repetitions?: number;
}

interface FlashcardReviewSM2Response {
  id: number;
  intervalo_dias: number;
  proxima_revisao: string;
  easiness_factor: number;
  repetitions: number;
  quality: number;
}

interface EditalItem {
  id: number;
  edital_nome: string;
  cargo: string;
  materia: string;
  topico: string;
  status: string;
  horas_estudadas: number;
  pdf_link?: string;
  pdf_pagina?: number;
}

interface EditalInfo {
  edital_nome: string;
  cargo: string;
  data_prova_objetiva?: string;
  data_prova_discursiva?: string;
  horario?: string;
  local_prova?: string;
  vagas?: string;
  subsidio?: string;
  inscricoes?: string;
  link_edital?: string;
}

interface EditalNome {
  concurso: string;
  cargos: { cargo: string; total: number; concluidos: number }[];
  total: number;
  concluidos: number;
}

interface Questao {
  id: number;
  materia: string;
  topico: string;
  enunciado: string;
  alternativa_a: string;
  alternativa_b: string;
  alternativa_c: string;
  alternativa_d: string;
  alternativa_e?: string;
  resposta_correta: string;
  explicacao?: string;
  dificuldade: string;
  banca?: string;
  created_at: string;
}

interface QuestaoResposta {
  acertou: boolean;
  resposta_correta: string;
}

interface ProgressData {
  current_page: number;
  total_pages: number;
}

interface TreeNode {
  type: 'folder' | 'pdf';
  name: string;
  path?: string;
  children?: TreeNode[];
}

interface StreakData {
  streak_atual: number;
  melhor_streak: number;
  hoje: {
    data: string;
    horas_estudadas: number;
    questoes_resolvidas: number;
    flashcards_revisados: number;
  };
}

interface MetasConfig {
  config: {
    meta_horas: number;
    meta_questoes: number;
    meta_flashcards: number;
    meta_paginas: number;
  };
  progresso: {
    horas: number;
    questoes: number;
    flashcards: number;
  };
}

interface CicloItem {
  id: number;
  materia: string;
  horas_alvo: number;
  horas_cumpridas: number;
  ordem: number;
  ativo: number;
}

interface Notificacao {
  tipo: string;
  icon: string;
  msg: string;
  prioridade: string;
}

interface GamificationData {
  xp: number;
  nivel: number;
  xp_no_nivel: number;
  xp_para_proximo: number;
  pct_nivel: number;
  badges_earned: { id: string; name: string; desc: string; icon: string }[];
  badges_total: number;
  stats: Record<string, number>;
}

interface CountdownItem {
  edital: string;
  cargo: string;
  data_objetiva: string;
  data_discursiva?: string;
  local?: string;
}

interface TreinadorResponse {
  score_prontidao: number;
  nivel: string;
  recomendacoes: { tipo: string; msg: string; materia?: string; qtd?: number }[];
  materias_foco: { materia: string; pct_acerto: number; prioridade: string }[];
  revisoes_pendentes: { flashcards: number; topicos: number };
  meta_hoje: Record<string, number>;
}

interface TrilhaAtividade {
  ordem: number;
  tipo: string;
  descricao?: string;
  materia?: string;
  topicos?: string[];
  qtd?: number;
  tempo_min: number;
}

interface TrilhaResponse {
  data: string;
  horas_disponiveis: number;
  atividades: TrilhaAtividade[];
  tempo_total_min: number;
  foco_principal: string;
  motivo?: string;
}

interface ApiOptions {
  method?: string;
  body?: any;
  retries?: number;
  timeout?: number;
}

interface SelectItem {
  icon?: string;
  label: string;
  sub?: string;
  value: any;
}

interface ShortcutDef {
  key: string;
  ctrl?: boolean;
  alt?: boolean;
  shift?: boolean;
  desc: string;
  action: () => void;
}

// ==================== GLOBAL DECLARATIONS ====================

declare var editalData: EditalItem[];
declare var Chart: any;
