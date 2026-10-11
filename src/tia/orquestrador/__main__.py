"""
Demonstração e comandos da Orquestração (EAP 1.3.5).

--demo: um aluno fictício (DEMO-O01, perfil intermediário; código, nunca
nome, R08) do início ao fim, num banco TEMPORÁRIO (não toca em data/tia.db):

    1. matrícula: o Planejador gera a trilha (o perfil dispensa variáveis,
       condicionais e repetição, pelo diagnóstico alto);
    2. acertos: conclui Funções -> R1: avança, replaneja só o que falta e avisa;
    3. queda: erra 3 vezes em Listas e strings -> R2: pausa a sessão e abre
       reforço do pré-requisito direto (Repetição) no nível 1;
    4. reforço: conclui Repetição -> retoma Listas e strings no nível em que parou;
    5. inatividade (datas simuladas: os horários do banco temporário são
       recuados) e verificação como o agendador faria: com 5 dias, só
       incentivo; com 15 dias (ORQ_INATIVIDADE_REFAZER_DIAS = 14), a trilha
       é refeita;
    6. termina a trilha; relatórios do aluno e da turma.

Imprime cada resposta (origem do feedback: LLM, guarda ou fallback, e o
motivo do fallback, ex.: timeout), cada decisão (motivo, aviso ao aluno e
origem das justificativas do Planejador) e, no fim, o tempo de cada etapa
separado em Tutor, Planejador, Relatório e o restante. R09 a medir na VM.

--verificar-inatividade: avalia a R3 em todos os alunos do banco
configurado (DB_PATH) e registra cada decisão na auditoria. É o comando
para o agendador externo (cron/timer na VM), que não faz parte deste pacote.

Como rodar (a partir da raiz, com o venv ativo):
    python -m tia.orquestrador --demo [--sem-llm]
    python -m tia.orquestrador --verificar-inatividade

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL e EMBED_MODEL (com --sem-llm, não precisa:
      todos os agentes usam os textos fixos)
    - Material indexado: python -m tia.rag.ingest (sem ele, feedback com o texto do item)
"""

import argparse
import itertools
import logging
import tempfile
import time
from pathlib import Path

import requests

import tia.core.database as database
import tia.core.llm_client as llm_client
from tia import orquestrador
from tia.agentes.relatorio import gerar_relatorio_aluno, gerar_relatorio_turma
from tia.agentes.relatorio.narrativa import formatar_texto_aluno
from tia.agentes.tutor import pergunta_atual
from tia.agentes.tutor.repositorio import carregar_itens
from tia.core.config import CHAT_MODEL, INATIVIDADE_DIAS, ORQ_INATIVIDADE_REFAZER_DIAS
from tia.orquestrador.modelos import EventoTutor, Matricula

ALUNO = "DEMO-O01"
MATRICULA = Matricula(perfil_id="intermediario", horas_semanais=6, diagnostico={
    "variaveis_tipos": 0.9, "condicionais": 0.8, "repeticao": 0.9,
    "funcoes": 0.2, "listas_strings": 0.2, "recursao": 0.0})
# (coluna, tabela) recuadas para simular dias sem atividade
HORARIOS = [("timestamp", "historico_respostas"), ("criado_em", "tutor_sessoes"), ("atualizado_em", "tutor_sessoes"),
            ("ts", "tutor_dialogo"), ("criado_em", "trilha_estudo"), ("ts", "orquestrador_decisoes"),
            ("ts", "auditoria")]
# trava de segurança da demonstração: nenhuma etapa deveria precisar de tantas respostas
MAXIMO_RESPOSTAS_POR_SESSAO = 20

contador = itertools.count(1)
gabarito = {i["id"]: i["indice_correto"] for i in carregar_itens()}
# tempos por etapa: total e partes (s); falhas do LLM por agente
tempos: dict[str, dict[str, float]] = {}
falhas: dict[str, int] = {"Tutor": 0, "Planejador": 0, "Relatório": 0}


def falha(texto: str | None) -> str:
    if not texto:
        return ""
    return " (TIMEOUT do LLM)" if texto == "timeout" else f" ({texto})"


def somar(etapa: str, parte: str, segundos: float):
    tempos.setdefault(etapa, {"total": 0.0, "Tutor": 0.0, "Planejador": 0.0, "Relatório": 0.0})[parte] += segundos


def imprimir_decisoes(decisoes, etapa: str):
    for d in decisoes:
        marca = "REPLANEJOU" if d.replanejou else "sem replanejar"
        print(f"   >>> DECISÃO [{d.regra}] {d.acao} ({marca}): {d.motivo}")
        if d.aviso:
            print(f"       aviso ao aluno: {d.aviso}")
        if d.replanejou:
            segundos = (d.tempo_planejador_ms or 0) / 1000
            somar(etapa, "Planejador", segundos)
            falhas["Planejador"] += d.falha_llm == "timeout"
            print(f"       Planejador: justificativas {d.origem_justificativas}{falha(d.falha_llm)} | {segundos:.1f} s")


def estudar(acertos: str, etapa: str):
    """Segue a próxima ação do orquestrador: abre a sessão por ele (ou
    continua a aberta) e responde ("1" acerta, "0" erra; depois do fim da
    sequência, acerta). Para quando a sessão conclui ou uma decisão muda o fluxo."""
    inicio = time.perf_counter()
    proxima = orquestrador.proxima(ALUNO)
    if proxima.acao == "iniciar_sessao":
        aberta = orquestrador.abrir_sessao(ALUNO, proxima.competencia_id)
        sessao_id, pergunta = aberta.sessao.sessao_id, aberta.sessao.pergunta
    else:  # continuar_sessao
        sessao_id, pergunta = proxima.sessao_id, pergunta_atual(proxima.sessao_id, ALUNO)
    tipo = "REFORÇO " if proxima.reforco else ""
    print(f"\n-- {proxima.acao} {tipo}em '{proxima.competencia_id}' ({proxima.motivo})")
    for n in range(MAXIMO_RESPOSTAS_POR_SESSAO):
        acerta = n >= len(acertos) or acertos[n] == "1"
        correto = gabarito[pergunta.item_id]
        resultado = orquestrador.processar_evento(ALUNO, EventoTutor(
            evento_id=f"evt-{next(contador):04d}", tipo="resposta", sessao_id=sessao_id, item_id=pergunta.item_id,
            indice_escolhido=correto if acerta else (correto + 1) % 4))
        fb = resultado.feedback
        somar(etapa, "Tutor", fb.tempo_ms / 1000)
        falhas["Tutor"] += fb.falha_llm == "timeout"
        print(f"   {pergunta.item_id}: {'ACERTOU' if fb.acertou else 'errou'} -> nível {fb.nivel_atual} "
              f"| feedback {fb.origem}{falha(fb.falha_llm)} | {fb.tempo_ms / 1000:.1f} s")
        imprimir_decisoes(resultado.decisoes, etapa)
        if fb.concluida or resultado.decisoes:
            break
        pergunta = fb.proxima_pergunta
    else:
        raise RuntimeError(f"A sessão não terminou em {MAXIMO_RESPOSTAS_POR_SESSAO} respostas.")
    somar(etapa, "total", time.perf_counter() - inicio)


def verificar(etapa: str):
    """Uma rodada da verificação de inatividade, como o agendador faria."""
    inicio = time.perf_counter()
    resultado = orquestrador.verificar_inatividade()
    for item in resultado.decisoes:
        imprimir_decisoes([item.decisao], etapa)
    somar(etapa, "total", time.perf_counter() - inicio)


def imprimir_tempos(total: float):
    print("\nTempo por etapa (s): total = Tutor + Planejador + Relatório + resto (orquestração, banco, regras)")
    print(f"   {'etapa':<12} {'total':>8} {'Tutor':>8} {'Planej.':>8} {'Relat.':>8} {'resto':>8}")
    for etapa, t in tempos.items():
        resto = t["total"] - t["Tutor"] - t["Planejador"] - t["Relatório"]
        print(f"   {etapa:<12} {t['total']:8.1f} {t['Tutor']:8.1f} {t['Planejador']:8.1f} {t['Relatório']:8.1f} "
              f"{resto:8.1f}")
    soma = {parte: sum(t[parte] for t in tempos.values()) for parte in ("Tutor", "Planejador", "Relatório")}
    print(f"   {'TOTAL':<12} {total:8.1f} {soma['Tutor']:8.1f} {soma['Planejador']:8.1f} {soma['Relatório']:8.1f} "
          f"{total - sum(soma.values()):8.1f}")
    print("Fallbacks por TIMEOUT do LLM: " + ", ".join(f"{agente} {n}" for agente, n in falhas.items()))
    print("(R09: até 15 s por interação, a medir na VM)")


def recuar_horarios(dias: int):
    """Simula a passagem do tempo no banco TEMPORÁRIO da demonstração."""
    conexao = database.obter_conexao()
    with conexao:
        for coluna, tabela in HORARIOS:
            conexao.execute(f"UPDATE {tabela} SET {coluna} = strftime('%Y-%m-%dT%H:%M:%S', {coluna}, ?) "
                            f"WHERE {coluna} IS NOT NULL", (f"-{dias} days",))
    conexao.close()


def sem_llm():
    """Toda chamada ao Ollama (chat e embedding) falha na hora: os agentes usam os textos fixos."""
    def falha_imediata(*args, **kwargs):
        raise requests.ConnectionError("demonstração com --sem-llm")
    llm_client.requests.post = falha_imediata


def demonstrar(com_llm: bool):
    pasta = tempfile.mkdtemp(prefix="tia_orquestrador_demo_")
    database.DB_PATH = str(Path(pasta) / "demo.db")
    database.criar_tabelas()
    print(f"\nBanco temporário: {database.DB_PATH} | modelo {CHAT_MODEL}{'' if com_llm else ' (sem LLM)'}")

    inicio_total = inicio = time.perf_counter()
    matricula = orquestrador.iniciar(ALUNO, MATRICULA)
    somar("matrícula", "total", time.perf_counter() - inicio)
    print(f"\n1. MATRÍCULA: trilha {' -> '.join(e.competencia_id for e in matricula.trilha.etapas)}")
    for e in matricula.trilha.etapas:
        print(f"   - {e.competencia_id}: [{e.origem_justificativa}] {e.justificativa}")
    imprimir_decisoes([matricula.decisao], "matrícula")

    print("\n2. ACERTOS")
    estudar("1111", "acertos")
    print("\n3. QUEDA")
    estudar("000", "queda")
    print("\n4. REFORÇO E RETOMADA")
    estudar("1111", "reforço")
    estudar("", "reforço")  # termina a competência retomada

    dias_refazer = ORQ_INATIVIDADE_REFAZER_DIAS + 1
    print(f"\n5. INATIVIDADE: {INATIVIDADE_DIAS + 2} dias sem atividade (verificação agendada)")
    recuar_horarios(INATIVIDADE_DIAS + 2)
    verificar("inatividade")
    print("   mesma verificação de novo (não repete):")
    verificar("inatividade")
    print(f"   ... {dias_refazer} dias sem atividade:")
    recuar_horarios(dias_refazer - (INATIVIDADE_DIAS + 2))
    verificar("inatividade")

    print("\n6. ATÉ O FIM")
    while orquestrador.proxima(ALUNO).acao != "concluido":
        estudar("", "fim")

    estado = orquestrador.estado(ALUNO)
    print(f"\nEstado final: concluído={estado.concluido}, etapas "
          f"{', '.join(e.competencia_id for e in estado.etapas)}, replanejamentos={estado.replanejamentos}")

    inicio = time.perf_counter()
    relatorio = gerar_relatorio_aluno(ALUNO, com_narrativa=com_llm)
    turma = gerar_relatorio_turma(com_narrativa=com_llm)
    segundos = time.perf_counter() - inicio
    somar("relatórios", "total", segundos)
    somar("relatórios", "Relatório", segundos)
    falhas["Relatório"] += relatorio.narrativa.falha_llm == "timeout"
    print("\n" + formatar_texto_aluno(relatorio))
    print(f"   (interpretação: {relatorio.narrativa.origem}{falha(relatorio.narrativa.falha_llm)})")
    print(f"\nRelatório da turma: alunos {turma.alunos.texto}, suprimido={turma.suprimido} (grupo mínimo LGPD)")
    imprimir_tempos(time.perf_counter() - inicio_total)


def verificar_inatividade_no_banco():
    """Comando para o agendador externo: R3 em todos os alunos do DB_PATH."""
    database.criar_tabelas()
    inicio = time.perf_counter()
    resultado = orquestrador.verificar_inatividade()
    for item in resultado.decisoes:
        d = item.decisao
        print(f"{item.aluno_id}: {d.acao} - {d.motivo}")
    print(f"{resultado.verificados} alunos verificados em {time.perf_counter() - inicio:.1f} s.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Orquestração: demonstração e verificação de inatividade.")
    parser.add_argument("--demo", action="store_true", help="executa o aluno fictício do início ao fim")
    parser.add_argument("--sem-llm", action="store_true", help="na demonstração, não chama o Ollama")
    parser.add_argument("--verificar-inatividade", action="store_true",
                        help="avalia a inatividade (R3) de todos os alunos do banco configurado")
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)

    if args.verificar_inatividade:
        verificar_inatividade_no_banco()
    elif args.demo:
        if args.sem_llm:
            sem_llm()
        demonstrar(com_llm=not args.sem_llm)
    else:
        parser.print_help()
