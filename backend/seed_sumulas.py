"""
Seed de Súmulas Vinculantes STF + Súmulas STJ/STF mais cobradas + Flashcards + Questões com mnemônicos.
Executar: python seed_sumulas.py
"""
import os
import sqlite3
from datetime import date

DB_PATH = os.environ.get("DB_PATH", "./progress.db")
TODAY = date.today().isoformat()

# ============================================================
# SÚMULAS VINCULANTES STF (ativas, mais relevantes para concursos)
# ============================================================
SUMULAS_VINCULANTES = [
    (1, "Ofende a garantia constitucional do ato jurídico perfeito a decisão que, sem ponderar as circunstâncias do caso concreto, desconsidera a validez e a eficácia de acordo constante de termo de adesão instituído pela Lei Complementar nº 110/2001.", "Direito Constitucional", "FGTS - acordo LC 110/2001"),
    (2, "É inconstitucional a lei ou ato normativo estadual ou distrital que disponha sobre sistemas de consórcios e sorteios, inclusive bingos e loterias.", "Direito Constitucional", "Competência privativa da União (art. 22, XX CF)"),
    (3, "Nos processos perante o Tribunal de Contas da União asseguram-se o contraditório e a ampla defesa quando da decisão puder resultar anulação ou revogação de ato administrativo que beneficie o interessado, excetuada a apreciação da legalidade do ato de concessão inicial de aposentadoria, reforma e pensão.", "Direito Administrativo", "TCU + contraditório. Exceção: concessão inicial de aposentadoria"),
    (4, "Salvo nos casos previstos na Constituição, o salário mínimo não pode ser usado como indexador de base de cálculo de vantagem de servidor público ou de empregado, nem ser substituído por decisão judicial.", "Direito Constitucional", "Salário mínimo NÃO pode ser indexador (art. 7º, IV CF)"),
    (5, "A falta de defesa técnica por advogado no processo administrativo disciplinar não ofende a Constituição.", "Direito Administrativo", "PAD sem advogado = válido (revogou Súmula 343 STJ)"),
    (10, "Viola a cláusula de reserva de plenário (CF, artigo 97) a decisão de órgão fracionário de tribunal que, embora não declare expressamente a inconstitucionalidade de lei ou ato normativo do poder público, afasta sua incidência, no todo ou em parte.", "Direito Constitucional", "Reserva de plenário = Full Bench"),
    (11, "Só é lícito o uso de algemas em casos de resistência e de fundado receio de fuga ou de perigo à integridade física própria ou alheia, por parte do preso ou de terceiros, justificada a excepcionalidade por escrito, sob pena de responsabilidade disciplinar, civil e penal do agente ou da autoridade e de nulidade da prisão ou do ato processual a que se refere, sem prejuízo da responsabilidade civil do Estado.", "Direito Processual Penal", "Algemas = excepcional, justificada por escrito"),
    (13, "A nomeação de cônjuge, companheiro ou parente em linha reta, colateral ou por afinidade, até o terceiro grau, inclusive, da autoridade nomeante ou de servidor da mesma pessoa jurídica investido em cargo de direção, chefia ou assessoramento, para o exercício de cargo em comissão ou de confiança ou, ainda, de função gratificada na administração pública direta e indireta em qualquer dos poderes da União, dos Estados, do Distrito Federal e dos Municípios, compreendido o ajuste mediante designações recíprocas, viola a Constituição Federal.", "Direito Administrativo", "Nepotismo. Até 3º grau. Inclui designações recíprocas (cruzado)"),
    (14, "É direito do defensor, no interesse do representado, ter acesso amplo aos elementos de prova que, já documentados em procedimento investigatório realizado por órgão com competência de polícia judiciária, digam respeito ao exercício do direito de defesa.", "Direito Processual Penal", "Acesso a provas DOCUMENTADAS na investigação"),
    (17, "Durante o período previsto no parágrafo 1º do artigo 100 da Constituição, não incidem juros de mora sobre os precatórios que nele sejam pagos.", "Direito Financeiro", "Precatório pago no prazo = sem juros de mora"),
    (21, "É inconstitucional a exigência de depósito ou arrolamento prévios de dinheiro ou bens para admissibilidade de recurso administrativo.", "Direito Administrativo", "Recurso administrativo NÃO precisa de depósito prévio"),
    (23, "A Justiça do Trabalho é competente para processar e julgar ação possessória ajuizada em decorrência do exercício do direito de greve pelos trabalhadores da iniciativa privada.", "Direito do Trabalho", "Greve + possessória = Justiça do Trabalho"),
    (25, "É ilícita a prisão civil de depositário infiel, qualquer que seja a modalidade do depósito.", "Direito Civil", "Única prisão civil = devedor de alimentos"),
    (26, "Para efeito de progressão de regime no cumprimento de pena por crime hediondo, ou equiparado, o juízo da execução observará a inconstitucionalidade do art. 2º da Lei nº 8.072, de 25 de julho de 1990, sem prejuízo de avaliar se o condenado preenche, ou não, os requisitos objetivos e subjetivos do benefício, podendo determinar, para tal fim, de modo fundamentado, a realização de exame criminológico.", "Direito Penal", "Crime hediondo ADMITE progressão de regime"),
    (27, "Compete à Justiça estadual julgar causas entre consumidor e concessionária de telefonia, quando a ANATEL não seja litisconsorte passiva necessária, assistente, nem opoente.", "Direito do Consumidor", "Consumidor vs telefonia = Justiça estadual (se ANATEL não participa)"),
    (29, "É constitucional a adoção, no cálculo do valor de taxa, de um ou mais elementos da base de cálculo própria de determinado imposto, desde que não haja integral identidade entre uma base e outra.", "Direito Tributário", "Taxa pode usar elementos de BC de imposto (não integral)"),
    (31, "É inconstitucional a incidência do imposto sobre serviços de qualquer natureza – ISS sobre operações de locação de bens móveis.", "Direito Tributário", "ISS NÃO incide sobre locação de bens móveis"),
    (33, "Aplicam-se ao servidor público, no que couber, as regras do regime geral da previdência social sobre aposentadoria especial de que trata o artigo 40, § 4º, inciso III da Constituição Federal, até a edição de lei complementar específica.", "Direito Previdenciário", "Servidor + aposentadoria especial = aplica RGPS até LC"),
    (37, "Não cabe ao Poder Judiciário, que não tem função legislativa, aumentar vencimentos de servidores públicos sob o fundamento de isonomia.", "Direito Administrativo", "Judiciário NÃO pode aumentar vencimentos por isonomia"),
    (47, "Os honorários advocatícios incluídos na condenação ou destacados do montante principal devido ao credor consubstanciam verba de natureza alimentar cuja satisfação ocorrerá com a expedição de precatório ou requisição de pequeno valor, apartado àquele destinado ao crédito principal.", "Direito Processual Civil", "Honorários = natureza alimentar, precatório próprio"),
    (50, "Norma legal que altera o prazo de recolhimento de obrigação tributária não se sujeita ao princípio da anterioridade.", "Direito Tributário", "Alterar prazo de recolhimento ≠ anterioridade"),
    (53, "A competência da Justiça do Trabalho prevista no art. 114, VIII, da Constituição Federal alcança a execução de ofício das contribuições previdenciárias relativas ao objeto da condenação constante das sentenças que proferir e acordos por ela homologados.", "Direito do Trabalho", "JT executa de ofício contribuições previdenciárias da condenação"),
    (56, "A falta de estabelecimento penal adequado não autoriza a manutenção do condenado em regime prisional mais gravoso, devendo-se observar, nessa hipótese, os parâmetros fixados no Recurso Extraordinário (RE) 641.320.", "Direito Penal", "Sem vaga = não pode manter regime mais gravoso"),
]

# ============================================================
# SÚMULAS STJ MAIS COBRADAS EM CONCURSOS (100 mais relevantes)
# ============================================================
SUMULAS_STJ = [
    (7, "A pretensão de simples reexame de prova não enseja recurso especial.", "Direito Processual Civil", "REsp não reexamina provas"),
    (54, "Os juros moratórios fluem a partir da citação.", "Direito Civil", "Mora ex persona = citação"),
    (83, "Não se conhece do recurso especial pela divergência, quando a orientação do Tribunal se firmou no mesmo sentido da decisão recorrida.", "Direito Processual Civil", "Divergência superada = REsp não conhecido"),
    (98, "Embargos de declaração manifestados com notório propósito de prequestionamento não têm caráter protelatório.", "Direito Processual Civil", "Prequestionamento via EDcl = não protelatório"),
    (126, "É inadmissível recurso especial, quando o acórdão recorrido assenta em fundamentos constitucional e infraconstitucional, qualquer deles suficiente, por si só, para mantê-lo, e a parte vencida não manifesta recurso extraordinário.", "Direito Processual Civil", "Fundamento duplo: precisa REsp + RE"),
    (150, "Compete à Justiça Federal decidir sobre a existência de interesse jurídico que justifique a presença, no processo, da União, suas autarquias ou empresas públicas.", "Direito Processual Civil", "JF decide se União tem interesse"),
    (211, "Inadmissível recurso especial quanto à questão que, a despeito da oposição de embargos declaratórios, não foi apreciada pelo Tribunal a quo.", "Direito Processual Civil", "Sem apreciação = sem prequestionamento"),
    (227, "A pessoa jurídica pode sofrer dano moral.", "Direito Civil", "PJ + dano moral = possível"),
    (229, "O pedido do pagamento de indenização à seguradora suspende o prazo de prescrição até que o segurado tenha ciência da decisão.", "Direito Civil", "Pedido à seguradora = suspende prescrição"),
    (231, "A incidência da contribuição previdenciária sobre o 13º salário não viola a Constituição Federal.", "Direito Tributário", "13º + INSS = constitucional"),
    (268, "O fiador que não integrou a relação processual na ação de despejo não responde pela execução do julgado.", "Direito Civil", "Fiador fora do processo = não executa"),
    (281, "A indenização por dano moral não está sujeita à tarifação prevista na Lei de Imprensa.", "Direito Civil", "Dano moral sem tarifação"),
    (297, "O Código de Defesa do Consumidor é aplicável às instituições financeiras.", "Direito do Consumidor", "CDC aplica a bancos"),
    (301, "A ação de investigação de paternidade tem natureza personalíssima e não se extingue com a morte do investigado.", "Direito Civil", "Investigação paternidade = não extingue com morte"),
    (309, "O débito alimentar que autoriza a prisão civil do alimentante é o que compreende até as 3 (três) prestações anteriores ao ajuizamento da execução e as que se vencerem no curso do processo.", "Direito Civil", "Prisão por alimentos: 3 últimas + vincendas"),
    (321, "O Código de Defesa do Consumidor é aplicável à relação jurídica entre a entidade de previdência privada e seus participantes.", "Direito do Consumidor", "CDC + previdência privada = aplicável"),
    (331, "A apelação interposta contra sentença que julga embargos à execução não terá efeito suspensivo.", "Direito Processual Civil", "Embargos à execução = apelação sem efeito suspensivo"),
    (375, "O reconhecimento da fraude à execução depende do registro da penhora do bem alienado ou da prova de má-fé do terceiro adquirente.", "Direito Processual Civil", "Fraude à execução: penhora registrada OU má-fé"),
    (385, "Da sentença que julgar parcialmente a lide caberá recurso de apelação.", "Direito Processual Civil", "Julgamento parcial = apelação (não agravo)"),
    (392, "O INSS não está obrigado a efetuar depósito prévio do preparo por gozar das prerrogativas e privilégios da Fazenda Pública.", "Direito Previdenciário", "INSS = Fazenda Pública (sem preparo)"),
    (410, "A prévia intimação pessoal do devedor constitui condição necessária para a cobrança de multa pelo descumprimento de obrigação de fazer ou não fazer.", "Direito Processual Civil", "Astreintes = precisa intimação pessoal"),
    (412, "A ação de repetição de indébito de tarifas de água e esgoto sujeita-se ao prazo prescricional estabelecido no Código Civil.", "Direito Civil", "Água/esgoto indébito = prescrição CC (10 anos)"),
    (479, "As instituições financeiras respondem objetivamente pelos danos gerados por fortuito interno relativo a fraudes e delitos praticados por terceiros no âmbito de operações bancárias.", "Direito do Consumidor", "Banco = responsabilidade objetiva por fraude"),
    (480, "O juízo da recuperação judicial não é competente para decidir sobre a constrição de bens não abrangidos pelo plano de recuperação da empresa.", "Direito Empresarial", "Juízo recuperação ≠ competente para bens fora do plano"),
    (498, "Não incide imposto de renda sobre a indenização por danos morais.", "Direito Tributário", "Dano moral = sem IR"),
    (501, "É cabível a aplicação retroativa da Lei 11.343/2006, desde que o resultado da incidência das suas disposições, na íntegra, seja mais favorável ao réu do que o advindo da aplicação da Lei 6.368/76, sendo vedada a combinação de leis.", "Direito Penal", "Lei de Drogas: retroage se mais favorável (não combina)"),
    (502, "Presentes a materialidade e a autoria, afigura-se típica, em relação ao crime previsto no artigo 184, inciso I, do Código Penal, a conduta de expor à venda CDs e DVDs piratas.", "Direito Penal", "Venda de DVDs piratas = típico (art. 184 CP)"),
    (511, "É possível a cumulação de indenização do dano material e do dano moral oriundos do mesmo fato.", "Direito Civil", "Dano material + moral = cumuláveis"),
    (568, "O relator, monocraticamente e no Superior Tribunal de Justiça, poderá dar ou negar provimento ao recurso quando houver entendimento dominante acerca do tema.", "Direito Processual Civil", "Relator decide monocrático se jurisprudência dominante"),
    (596, "A obrigação alimentar dos avós tem natureza complementar e subsidiária, somente se configurando no caso de impossibilidade total ou parcial de seu cumprimento pelos pais.", "Direito Civil", "Avós = alimentos subsidiários"),
    (630, "A incidência da atenuante da confissão espontânea no cálculo da pena não se aplica quando o agente confessa a prática do crime perante a autoridade policial, mas a nega em juízo.", "Direito Penal", "Confissão retratada parcialmente = não atenua"),
    (647, "São da competência da Justiça Federal as ações contra o INSS, ainda que o trabalhador tenha perdido a condição de segurado.", "Direito Processual Civil", "Ação vs INSS = sempre Justiça Federal"),
]

# ============================================================
# SÚMULAS STF (simples) MAIS COBRADAS
# ============================================================
SUMULAS_STF = [
    (266, "Não cabe mandado de segurança contra lei em tese.", "Direito Constitucional", "MS ≠ lei em tese (norma abstrata)"),
    (267, "Não cabe mandado de segurança contra ato judicial passível de recurso ou correição.", "Direito Constitucional", "MS ≠ ato judicial recorrível"),
    (269, "O mandado de segurança não é substitutivo de ação de cobrança.", "Direito Constitucional", "MS ≠ cobrança"),
    (279, "Para simples reexame de prova não cabe recurso extraordinário.", "Direito Processual Civil", "RE não reexamina prova (= Súmula 7 STJ)"),
    (280, "Por ofensa a direito local não cabe recurso extraordinário.", "Direito Processual Civil", "Direito local = sem RE"),
    (323, "É inadmissível a apreensão de mercadorias como meio coercitivo para pagamento de tributos.", "Direito Tributário", "Apreender mercadoria para cobrar tributo = inconstitucional"),
    (339, "Não cabe ao Poder Judiciário, que não tem função legislativa, aumentar vencimentos de servidores públicos sob fundamento de isonomia.", "Direito Administrativo", "= SV 37"),
    (346, "A administração pública pode declarar a nulidade dos seus próprios atos.", "Direito Administrativo", "Autotutela (complementa Súmula 473)"),
    (347, "O Tribunal de Contas, no exercício de suas atribuições, pode apreciar a constitucionalidade das leis e dos atos do poder público.", "Direito Constitucional", "TCU aprecia constitucionalidade"),
    (356, "O ponto omisso da decisão, sobre o qual não foram opostos embargos declaratórios, não pode ser objeto de recurso extraordinário, por faltar o requisito do prequestionamento.", "Direito Processual Civil", "Sem EDcl em ponto omisso = sem prequestionamento"),
    (473, "A administração pode anular seus próprios atos, quando eivados de vícios que os tornam ilegais, porque deles não se originam direitos; ou revogá-los, por motivo de conveniência ou oportunidade, respeitados os direitos adquiridos, e ressalvada, em todos os casos, a apreciação judicial.", "Direito Administrativo", "AUTOTUTELA: anula (ilegal) ou revoga (conveniência). A mais cobrada!"),
    (683, "O limite de idade para a inscrição em concurso público só se legitima em face do art. 7º, XXX, da Constituição, quando possa ser justificado pela natureza das atribuições do cargo a ser preenchido.", "Direito Administrativo", "Limite de idade em concurso = só se justificado pela natureza do cargo"),
    (684, "É inconstitucional o veto não motivado à participação de candidato a concurso público.", "Direito Administrativo", "Veto sem motivação em concurso = inconstitucional"),
    (735, "Não cabe recurso extraordinário contra acórdão que defere medida liminar.", "Direito Processual Civil", "Liminar = sem RE"),
    (736, "Compete à Justiça do Trabalho julgar as ações que tenham como causa de pedir o descumprimento de normas trabalhistas relativas à segurança, higiene e saúde dos trabalhadores.", "Direito do Trabalho", "Norma trabalhista de segurança = Justiça Trabalho"),
]

# ============================================================
# FLASHCARDS COM DICAS DE MEMORIZAÇÃO
# ============================================================
FLASHCARDS = [
    # Súmulas Vinculantes
    ("SV 5: Precisa de advogado no PAD?", "NÃO. A falta de defesa técnica por advogado no PAD não ofende a CF.\n\n💡 DICA: 'PAD sem AD(vogado) = 5 letras, SV 5'", "Súmulas Vinculantes"),
    ("SV 11: Quando pode usar algemas?", "Apenas: resistência, receio de fuga, perigo à integridade física. Deve ser justificada POR ESCRITO.\n\n💡 MNEMÔNICO: 'RFP' = Resistência, Fuga, Perigo (11 letras = SV 11)", "Súmulas Vinculantes"),
    ("SV 13: O que é nepotismo?", "Nomeação de cônjuge/parente até 3º grau para cargo em comissão/confiança. Inclui 'cruzado' (designações recíprocas).\n\n💡 DICA: '13 = azarado quem pratica nepotismo'", "Súmulas Vinculantes"),
    ("SV 14: Qual o direito do defensor na investigação?", "Acesso amplo a provas JÁ DOCUMENTADAS. NÃO inclui diligências em andamento.\n\n💡 DICA: 'SV 14 = 14 letras em DOCUMENTADAS (quase!)'", "Súmulas Vinculantes"),
    ("SV 21: Pode exigir depósito para recurso administrativo?", "NÃO. É inconstitucional exigir depósito/arrolamento prévio para recurso administrativo.\n\n💡 DICA: 'Recurso admin é DE GRAÇA = 21'", "Súmulas Vinculantes"),
    ("SV 25: Pode prender depositário infiel?", "NÃO. É ilícita qualquer prisão civil de depositário infiel.\n\n💡 DICA: 'Só presa por ALImentos (25 = vinte e CINCO = CINCO letras em ALIme)'", "Súmulas Vinculantes"),
    ("SV 37: Judiciário pode aumentar salário de servidor por isonomia?", "NÃO. Judiciário não tem função legislativa.\n\n💡 DICA: 'SV 37 = art. 37 CF (administração pública)'", "Súmulas Vinculantes"),
    ("SV 50: Alterar prazo de recolhimento de tributo respeita anterioridade?", "NÃO precisa. Norma que altera prazo de recolhimento não se sujeita à anterioridade.\n\n💡 DICA: 'Prazo ≠ criação/aumento de tributo'", "Súmulas Vinculantes"),
    ("SV 56: Falta de vaga permite regime mais gravoso?", "NÃO. A falta de estabelecimento adequado não autoriza regime mais gravoso.\n\n💡 DICA: '56 = o Estado que se vire, não o preso'", "Súmulas Vinculantes"),
    ("Súmula 473 STF: O que é autotutela administrativa?", "A administração ANULA atos ilegais e REVOGA por conveniência/oportunidade, respeitados direitos adquiridos.\n\n💡 MNEMÔNICO: 'ANULA = ilegal / REVOGA = inconveniente'", "Súmulas STF"),
    # Súmulas STJ
    ("Súmula 7 STJ: Cabe REsp para reexame de prova?", "NÃO. Simples reexame de prova não enseja recurso especial.\n\n💡 DICA: '7 pecados = não pode reexaminar prova no REsp'", "Súmulas STJ"),
    ("Súmula 297 STJ: CDC aplica a bancos?", "SIM. O CDC é aplicável às instituições financeiras.\n\n💡 DICA: '297 = banco 24h (2+9+7=18, quase 24!)'", "Súmulas STJ"),
    ("Súmula 227 STJ: PJ pode sofrer dano moral?", "SIM. A pessoa jurídica pode sofrer dano moral.\n\n💡 DICA: 'PJ 2 letras + 27 = 227'", "Súmulas STJ"),
    ("Súmula 309 STJ: Quantas prestações atrasadas autorizam prisão do devedor de alimentos?", "As 3 últimas ANTES do ajuizamento + as que vencerem no curso do processo.\n\n💡 DICA: '309 = 3 parcelas + 09 (vem depois = vincendas)'", "Súmulas STJ"),
    ("Súmula 375 STJ: Quando há fraude à execução?", "Quando há registro de penhora OU prova de má-fé do terceiro adquirente.\n\n💡 DICA: 'Fraude = Registro OU Má-fé'", "Súmulas STJ"),
    ("Súmula 479 STJ: Banco responde por fraude de terceiro?", "SIM. Responsabilidade OBJETIVA por fortuito INTERNO (fraudes em operações bancárias).\n\n💡 DICA: 'Banco arca com golpe = 479 (4+7+9=20 = vinte = VINTE dedos que digitaram a fraude)'", "Súmulas STJ"),
    ("Súmula 498 STJ: Incide IR sobre indenização por dano moral?", "NÃO. Não incide imposto de renda sobre indenização por danos morais.\n\n💡 DICA: 'Dor não paga imposto'", "Súmulas STJ"),
    ("Súmula 596 STJ: Avós são obrigados a pagar alimentos?", "SIM, mas de forma COMPLEMENTAR e SUBSIDIÁRIA (só se pais não podem).\n\n💡 DICA: 'Avós = plano B dos alimentos'", "Súmulas STJ"),
]

# ============================================================
# QUESTÕES COM MNEMÔNICOS E EXPLICAÇÕES
# ============================================================
QUESTOES = [
    {
        "materia": "Direito Administrativo",
        "topico": "Súmulas Vinculantes",
        "enunciado": "Sobre as súmulas vinculantes do STF, assinale a alternativa CORRETA:",
        "a": "A falta de advogado no PAD ofende o devido processo legal (SV 5)",
        "b": "É lícito o uso de algemas sempre que o preso estiver em deslocamento (SV 11)",
        "c": "A nomeação de parente até 3º grau para cargo em comissão configura nepotismo (SV 13)",
        "d": "É constitucional a exigência de depósito prévio para recurso administrativo (SV 21)",
        "e": "O Judiciário pode aumentar vencimentos de servidores por isonomia (SV 37)",
        "resposta": "C",
        "explicacao": "SV 13: nepotismo = parente até 3º grau em cargo de comissão/confiança. Inclui cruzado.\n\n🧠 MNEMÔNICO: 'NEPOTISMO = NE(fasto) + 3ºGrau + COMISSÃO'\n\nAs outras estão invertidas: SV5=não precisa advogado; SV11=algema é exceção; SV21=depósito é inconstitucional; SV37=judiciário não pode.",
        "dificuldade": "Fácil",
        "banca": "CESPE",
    },
    {
        "materia": "Direito Administrativo",
        "topico": "Autotutela",
        "enunciado": "De acordo com a Súmula 473 do STF, a administração pública pode:",
        "a": "Apenas revogar seus atos, nunca anulá-los sem decisão judicial",
        "b": "Anular atos ilegais e revogar por conveniência, respeitados direitos adquiridos",
        "c": "Anular atos por conveniência e revogar atos ilegais",
        "d": "Anular e revogar quaisquer atos, sem limitação temporal",
        "e": "Apenas anular seus atos, devendo a revogação ser feita pelo Legislativo",
        "resposta": "B",
        "explicacao": "Súmula 473 STF = AUTOTUTELA:\n- ANULA = vício de LEGALIDADE (efeito ex tunc)\n- REVOGA = CONVENIÊNCIA/OPORTUNIDADE (efeito ex nunc)\n- Limite: direitos adquiridos + apreciação judicial\n\n🧠 MNEMÔNICO: 'A-I-R-C' = Anula-Ilegal / Revoga-Conveniência",
        "dificuldade": "Fácil",
        "banca": "FCC",
    },
    {
        "materia": "Direito Civil",
        "topico": "Súmulas STJ",
        "enunciado": "Segundo o entendimento sumulado do STJ, é CORRETO afirmar que:",
        "a": "A pessoa jurídica não pode sofrer dano moral por não ter sentimentos",
        "b": "O fiador que não participou da ação de despejo responde pela execução",
        "c": "Os juros moratórios fluem a partir da citação (Súmula 54)",
        "d": "A prescrição da ação de repetição de tarifas de água é de 5 anos",
        "e": "A obrigação alimentar dos avós é principal e solidária",
        "resposta": "C",
        "explicacao": "Súmula 54 STJ: juros moratórios fluem a partir da CITAÇÃO.\n\n🧠 MNEMÔNICO: 'CITação = CInquenta e quaTro (54)'\n\nErros: A=Súm.227 diz PJ PODE; B=Súm.268 fiador FORA não responde; D=prescrição CC 10 anos; E=avós são SUBSIDIÁRIOS (Súm.596)",
        "dificuldade": "Médio",
        "banca": "CESPE",
    },
    {
        "materia": "Direito do Consumidor",
        "topico": "Súmulas STJ",
        "enunciado": "Acerca da aplicação do CDC conforme súmulas do STJ, assinale a INCORRETA:",
        "a": "O CDC é aplicável às instituições financeiras (Súmula 297)",
        "b": "O CDC é aplicável à relação entre previdência privada e participantes (Súmula 321)",
        "c": "Instituições financeiras respondem objetivamente por fraudes bancárias (Súmula 479)",
        "d": "O CDC não se aplica a contratos de plano de saúde por serem regulados pela ANS",
        "e": "A indenização por dano moral não está sujeita à tarifação (Súmula 281)",
        "resposta": "D",
        "explicacao": "O CDC SE APLICA a planos de saúde! A regulação pela ANS não exclui a proteção consumerista.\n\n🧠 MNEMÔNICO para lembrar onde o CDC aplica: 'BPP' = Bancos (297) + Previdência Privada (321) + Planos de saúde\n\nTodas as outras alternativas estão corretas conforme as súmulas citadas.",
        "dificuldade": "Médio",
        "banca": "FCC",
    },
    {
        "materia": "Direito Processual Penal",
        "topico": "Súmulas Vinculantes",
        "enunciado": "A Súmula Vinculante 11, que trata do uso de algemas, estabelece que:",
        "a": "O uso de algemas é sempre proibido durante audiências judiciais",
        "b": "O uso é lícito apenas em casos de resistência, receio de fuga ou perigo à integridade, justificado por escrito",
        "c": "O uso de algemas é permitido livremente durante o transporte de presos",
        "d": "Apenas presos condenados por crimes hediondos podem ser algemados",
        "e": "O uso depende de autorização judicial prévia",
        "resposta": "B",
        "explicacao": "SV 11: Algemas = EXCEÇÃO, não regra.\nRequisitos cumulativos:\n1) Resistência OU receio de fuga OU perigo à integridade\n2) Justificativa POR ESCRITO\nSob pena de: responsabilidade disciplinar, civil e penal + nulidade\n\n🧠 MNEMÔNICO: 'RFP + ESCRITO' (Resistência, Fuga, Perigo + documento escrito)",
        "dificuldade": "Fácil",
        "banca": "CESPE",
    },
    {
        "materia": "Direito Tributário",
        "topico": "Súmulas Vinculantes",
        "enunciado": "Em matéria tributária, as Súmulas Vinculantes do STF estabelecem que:",
        "a": "O ISS incide normalmente sobre locação de bens móveis",
        "b": "A taxa pode utilizar integralmente a base de cálculo de um imposto",
        "c": "Norma que altera prazo de recolhimento NÃO se sujeita à anterioridade (SV 50)",
        "d": "A apreensão de mercadorias para pagamento de tributos é constitucional",
        "e": "O depósito prévio é requisito para recurso administrativo tributário",
        "resposta": "C",
        "explicacao": "SV 50: Alterar PRAZO de recolhimento ≠ criar/aumentar tributo, logo NÃO se sujeita à anterioridade.\n\n🧠 MNEMÔNICO: 'PRAZO é logístico, não econômico'\n\nErros: A=SV31 ISS NÃO incide locação móveis; B=SV29 taxa pode usar ELEMENTOS (não integral); D=Súm.323 STF é inadmissível; E=SV21 depósito é inconstitucional",
        "dificuldade": "Médio",
        "banca": "CESPE",
    },
]


def seed():
    conn = sqlite3.connect(DB_PATH)

    # ===== SÚMULAS =====
    count_sumulas = 0

    # Vinculantes STF
    for num, enunciado, tema, obs in SUMULAS_VINCULANTES:
        existing = conn.execute("SELECT id FROM sumulas WHERE tribunal = 'STF' AND numero = ? AND vinculante = 1 AND user_id = 1", (num,)).fetchone()
        if not existing:
            conn.execute("""
                INSERT INTO sumulas (tribunal, numero, enunciado, tema, observacao, vinculante, proxima_revisao, user_id)
                VALUES (?, ?, ?, ?, ?, 1, ?, 1)
            """, ("STF", num, enunciado, tema, obs, TODAY))
            count_sumulas += 1

    # STJ
    for num, enunciado, tema, obs in SUMULAS_STJ:
        existing = conn.execute("SELECT id FROM sumulas WHERE tribunal = 'STJ' AND numero = ? AND user_id = 1", (num,)).fetchone()
        if not existing:
            conn.execute("""
                INSERT INTO sumulas (tribunal, numero, enunciado, tema, observacao, vinculante, proxima_revisao, user_id)
                VALUES (?, ?, ?, ?, ?, 0, ?, 1)
            """, ("STJ", num, enunciado, tema, obs, TODAY))
            count_sumulas += 1

    # STF simples
    for num, enunciado, tema, obs in SUMULAS_STF:
        existing = conn.execute("SELECT id FROM sumulas WHERE tribunal = 'STF' AND numero = ? AND vinculante = 0 AND user_id = 1", (num,)).fetchone()
        if not existing:
            conn.execute("""
                INSERT INTO sumulas (tribunal, numero, enunciado, tema, observacao, vinculante, proxima_revisao, user_id)
                VALUES (?, ?, ?, ?, ?, 0, ?, 1)
            """, ("STF", num, enunciado, tema, obs, TODAY))
            count_sumulas += 1

    # ===== FLASHCARDS =====
    count_flash = 0
    for pergunta, resposta, materia in FLASHCARDS:
        existing = conn.execute("SELECT id FROM flashcards WHERE pergunta = ? AND user_id = 1", (pergunta,)).fetchone()
        if not existing:
            conn.execute("""
                INSERT INTO flashcards (pergunta, resposta, proxima_revisao, materia, user_id)
                VALUES (?, ?, ?, ?, 1)
            """, (pergunta, resposta, TODAY, materia))
            count_flash += 1

    # ===== QUESTÕES =====
    count_quest = 0
    for q in QUESTOES:
        existing = conn.execute("SELECT id FROM questoes WHERE enunciado = ? AND user_id = 1", (q["enunciado"],)).fetchone()
        if not existing:
            conn.execute("""
                INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, alternativa_c,
                    alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, banca, created_at, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (q["materia"], q["topico"], q["enunciado"], q["a"], q["b"], q["c"],
                  q["d"], q["e"], q["resposta"], q["explicacao"], q["dificuldade"], q["banca"], TODAY))
            count_quest += 1

    conn.commit()
    conn.close()

    print(f"""
✅ Seed concluído!
   📜 Súmulas: {count_sumulas} inseridas
      - Vinculantes STF: {len(SUMULAS_VINCULANTES)}
      - STJ: {len(SUMULAS_STJ)}
      - STF simples: {len(SUMULAS_STF)}
   🃏 Flashcards: {count_flash} inseridos (com dicas + mnemônicos)
   ❓ Questões: {count_quest} inseridas (com explicações + mnemônicos)
""")


if __name__ == "__main__":
    seed()
