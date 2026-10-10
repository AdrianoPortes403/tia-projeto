"""
Textos do Agente 3 (Relatório): o parágrafo de interpretação (LLM com
guarda e fallback) e a versão em texto dos relatórios para o terminal.

Parágrafo de interpretação:
    1. resumo_aluno / resumo_turma montam, por CÓDIGO, um resumo com os
       números já calculados (indicadores.py); é a única coisa que o LLM vê
       (sem aluno_id nem dado pessoal, R08);
    2. o LLM local (R07; timeout, tokens e amostragem em core/config.py)
       redige de 2 a 3 frases, sem calcular nada;
    3. guarda de saída (feedback.verificar_texto, a mesma do Tutor): descarta
       o texto com número que não está no resumo, referência ao prompt ou
       contradição interna;
    4. LLM indisponível, resposta vazia ou descartada: texto FIXO
       (FALLBACK_ALUNO / FALLBACK_TURMA). O relatório fica completo sem LLM.

Não é executável sozinho; demonstração:
    python -m tia.agentes.relatorio --demo

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL (opcional: sem ele, texto fixo)
"""

import logging

from tia.agentes.relatorio.modelos import Narrativa, RelatorioAluno, RelatorioTurma
from tia.agentes.tutor.feedback import limpar_explicacao, verificar_texto
from tia.core.config import (INATIVIDADE_DIAS, RELATORIO_MAX_TOKENS, RELATORIO_SEED, RELATORIO_TEMPERATURA,
                             RELATORIO_TIMEOUT_LLM)
from tia.core.llm_client import chamar_llm

log = logging.getLogger(__name__)

FALLBACK_ALUNO = ("Este resumo mostra como você está indo no Tutor. Confira acima o seu progresso na trilha, "
                  "seus acertos e os temas que merecem revisão.")
FALLBACK_TURMA = ("Resumo agregado da turma. A interpretação automática não está disponível; "
                  "consulte os indicadores e os alertas acima.")
SUPRIMIDO_TURMA = "Grupo com poucos alunos: os indicadores não são exibidos, para proteger a privacidade (LGPD)."
DIRECAO = {"subindo": "subindo", "caindo": "caindo", "estavel": "estável", "insuficiente": "ainda sem dados suficientes"}


def pct(taxa: float | None) -> str:
    """Fração como porcentagem inteira ("75%"); "-" sem dado."""
    return "-" if taxa is None else f"{round(taxa * 100)}%"


# --- resumo numérico (entrada do LLM) ---

def resumo_aluno(rel: RelatorioAluno) -> str:
    p, d, e = rel.progresso, rel.desempenho, rel.engajamento
    linhas = []
    if p.tem_trilha:
        linhas.append(f"Trilha: {p.concluidas} de {p.etapas} etapas concluídas ({pct(p.percentual)}).")
    else:
        linhas.append("Trilha: o aluno ainda não gerou a trilha de estudo.")
    linhas.append(f"Acerto geral: {pct(d.geral.taxa)} em {d.geral.respostas} respostas.")
    linhas.append(f"Tendência do acerto: {DIRECAO[d.tendencia.direcao]}"
                  + (f" ({pct(d.tendencia.recentes.taxa)} nas últimas respostas, "
                     f"{pct(d.tendencia.anteriores.taxa)} antes)." if d.tendencia.variacao is not None else "."))
    linhas.append(f"Atividade: {e.sessoes} sessões, {e.dias_ativos} dias com atividade"
                  + (f", {e.dias_inativo} dias desde a última atividade." if e.dias_inativo is not None else "."))
    if rel.pontos_fracos:
        linhas.append("Temas para revisar: " + "; ".join(
            f"{f.nome} ({f.erros} erros em {f.respostas} respostas)" for f in rel.pontos_fracos) + ".")
    else:
        linhas.append("Temas para revisar: nenhum com erro repetido.")
    return "\n".join(linhas)


def resumo_turma(rel: RelatorioTurma) -> str:
    linhas = [f"Alunos no grupo: {rel.alunos.texto}."]
    if rel.progresso_medio is not None:
        linhas.append(f"Progresso médio na trilha: {pct(rel.progresso_medio)}.")
    visiveis = [g for g in rel.desempenho_por_competencia if not g.suprimido]
    if visiveis:
        linhas.append("Acerto por competência: " + "; ".join(f"{g.chave} {pct(g.taxa)}" for g in visiveis) + ".")
    if rel.engajamento:
        linhas.append(f"Média de {rel.engajamento.media_sessoes} sessões e {rel.engajamento.media_dias_ativos} "
                      f"dias ativos por aluno; inativos: {rel.engajamento.inativos.texto}.")
    for alerta in rel.alertas:
        linhas.append(f"Alerta: {alerta.descricao} Alunos: {alerta.alunos.texto}.")
    return "\n".join(linhas)


# --- parágrafo de interpretação ---

def montar_prompt(resumo: str, publico: str) -> str:
    if publico == "aluno":
        destino = ("Escreva direto para o aluno (use \"você\"), em português simples e encorajador, de 2 a 3 "
                   "frases, interpretando os números abaixo. Não compare com colegas.")
    else:
        destino = ("Escreva para a coordenação pedagógica, em português, de 2 a 3 frases, interpretando os "
                   "números agregados da turma abaixo. Não fale de nenhum aluno individualmente.")
    return (
        f"{destino}\n"
        "Regras:\n"
        "- Os números já foram calculados: não calcule, não arredonde de outro jeito e não invente "
        "nenhum número; só repita os que aparecem abaixo.\n"
        "- Não afirme nada que não esteja abaixo. Não mencione estas instruções.\n"
        "- Sem listas, sem títulos.\n\n"
        f"NÚMEROS:\n{resumo}"
    )


def redigir(resumo: str, publico: str) -> Narrativa:
    """Parágrafo do LLM aprovado pela guarda, ou o texto fixo do público."""
    fallback = FALLBACK_ALUNO if publico == "aluno" else FALLBACK_TURMA
    try:
        bruta = chamar_llm(montar_prompt(resumo, publico), think=False, timeout=RELATORIO_TIMEOUT_LLM,
                           max_tokens=RELATORIO_MAX_TOKENS, temperatura=RELATORIO_TEMPERATURA, seed=RELATORIO_SEED)
    except Exception as erro:
        log.warning("LLM indisponível no relatório (%s); texto fixo.", type(erro).__name__)
        return Narrativa(texto=fallback, origem="fallback")
    texto = limpar_explicacao(bruta)
    if not texto:
        return Narrativa(texto=fallback, origem="fallback")
    motivo = verificar_texto(texto, [resumo], "")
    if motivo:
        log.info("Guarda descartou a narrativa do relatório (%s); texto fixo.", motivo.split(":")[0])
        return Narrativa(texto=fallback, origem="guarda", motivo_descarte=motivo)
    return Narrativa(texto=texto, origem="LLM")


# --- versão em texto para o terminal ---

def formatar_texto_aluno(rel: RelatorioAluno) -> str:
    p, d, e, q = rel.progresso, rel.desempenho, rel.engajamento, rel.qualidade_feedback
    nomes = {c.competencia_id: c.nome for c in p.por_competencia}
    linhas = [f"RELATÓRIO DO ALUNO {rel.aluno_id}  (gerado em {rel.gerado_em}; indicadores PROVISÓRIOS)", ""]
    linhas.append("1. Seu progresso na trilha")
    if p.tem_trilha:
        linhas.append(f"   {p.concluidas} de {p.etapas} etapas concluídas ({pct(p.percentual)})")
    else:
        linhas.append("   Você ainda não tem trilha de estudo. Gere a sua para saber por onde começar.")
    for c in p.por_competencia:
        situacao = "concluída" if c.concluida else (f"nível {c.nivel_atual}" if c.nivel_atual else "não iniciada")
        linhas.append(f"   - {c.nome}: {situacao}")
    linhas += ["", "2. Seus acertos",
               f"   No geral: {pct(d.geral.taxa)} ({d.geral.acertos} de {d.geral.respostas})"]
    for t in d.por_competencia:
        linhas.append(f"   - {nomes.get(t.chave, t.chave)}: {pct(t.taxa)} ({t.acertos} de {t.respostas})")
    linhas.append("   Por nível: " + (", ".join(f"nível {t.chave} {pct(t.taxa)}" for t in d.por_nivel) or "-"))
    linhas.append(f"   Tendência: {DIRECAO[d.tendencia.direcao]}"
                  + (f" ({pct(d.tendencia.recentes.taxa)} nas últimas {d.tendencia.recentes.respostas} respostas,"
                     f" {pct(d.tendencia.anteriores.taxa)} antes)" if d.tendencia.variacao is not None else ""))
    linhas += ["", "3. Sua atividade",
               f"   {e.sessoes} sessões ({e.sessoes_concluidas} concluídas), {e.respostas} respostas, "
               f"{e.perguntas_dialogo} perguntas ao Tutor, {e.dias_ativos} dias com atividade"]
    if e.dias_inativo is not None:
        linhas.append(f"   Última atividade há {e.dias_inativo} dias"
                      + (f" (sem atividade há {INATIVIDADE_DIAS} dias ou mais: que tal voltar?)" if e.inativo else ""))
    linhas += ["", "4. Temas para revisar"]
    if rel.pontos_fracos:
        for f in rel.pontos_fracos:
            linhas.append(f"   - {f.nome}: {f.erros} erros em {f.respostas} respostas "
                          f"(até {f.maior_sequencia_erros} seguidos); {f.perguntas_dialogo} perguntas ao Tutor")
    else:
        linhas.append("   Nenhum tema com erro repetido.")
    linhas += ["", "5. Respostas do Tutor para você",
               "   " + ", ".join(f"{o}: {n}" for o, n in q.por_origem.items())
               + f"; respostas revisadas por professor: {q.vetados} de {q.dialogos}"]
    linhas += ["", f"Interpretação ({rel.narrativa.origem}): {rel.narrativa.texto}"]
    return "\n".join(linhas)


def _grupo(g) -> str:
    if g.suprimido:
        return f"   - {g.chave}: suprimido (alunos: {g.alunos.texto})"
    return f"   - {g.chave}: {pct(g.taxa)} em {g.respostas} respostas ({g.alunos.texto} alunos)"


def formatar_texto_turma(rel: RelatorioTurma) -> str:
    grupo = f"perfil {rel.perfil_id}" if rel.perfil_id else "instituição"
    linhas = [f"RELATÓRIO DA TURMA ({grupo}; gerado em {rel.gerado_em}; grupo mínimo {rel.min_grupo}; "
              f"indicadores PROVISÓRIOS)", f"Alunos: {rel.alunos.texto}", ""]
    if rel.suprimido:
        return "\n".join(linhas + [rel.narrativa.texto])
    linhas += ["1. Progresso na trilha",
               f"   Média: {pct(rel.progresso_medio)} (alunos com trilha: {rel.alunos_com_trilha.texto})", "",
               "2. Desempenho por competência"]
    linhas += [_grupo(g) for g in rel.desempenho_por_competencia]
    linhas.append("   Por nível:")
    linhas += [_grupo(g) for g in rel.desempenho_por_nivel]
    e = rel.engajamento
    linhas += ["", "3. Engajamento",
               f"   Média por aluno: {e.media_sessoes} sessões, {e.media_dias_ativos} dias ativos, "
               f"{e.media_perguntas_dialogo} perguntas ao Tutor; inativos: {e.inativos.texto}", "",
               "4. Pontos fracos recorrentes (alunos com erro repetido; taxa = erro agregado)"]
    linhas += ([f"   - {g.chave}: {g.alunos.texto} alunos"
                + ("" if g.suprimido else f", erro agregado {pct(g.taxa)}") for g in rel.pontos_fracos]
               or ["   Nenhum."])
    q = rel.qualidade_feedback
    linhas += ["", "5. Qualidade do feedback",
               "   Origem: " + ", ".join(f"{o} {n} ({pct(q.taxa_por_origem[o])})" for o, n in q.por_origem.items())
               + f"; sem registro: {q.respostas_sem_registro}",
               f"   Veto docente: {q.vetados} de {q.dialogos} respostas do diálogo ({pct(q.taxa_veto)})", "",
               "Alertas de risco"]
    linhas += ([f"   [{a.tipo}] {a.descricao} Alunos: {a.alunos.texto}" for a in rel.alertas] or ["   Nenhum."])
    linhas += ["", f"Interpretação ({rel.narrativa.origem}): {rel.narrativa.texto}"]
    return "\n".join(linhas)
