"""
Demonstração e linha de comando do Agente 3 (Relatório).

--demo: cria um banco TEMPORÁRIO (não toca em data/tia.db) com 6 alunos
fictícios (DEMO-R01 a DEMO-R06; códigos, nunca nomes, R08) e padrões
diferentes: constante, em queda, inativo, com dificuldade em repetição e
dois do perfil intermediário. As respostas gravam item_id e sessao_id,
exceto as do DEMO-R06, que simulam respostas antigas (NULL) para mostrar
o comportamento sem esses campos. Imprime o relatório de um aluno, o da
instituição e o do perfil "iniciante" (4 alunos: suprimido, abaixo do
grupo mínimo), cada um com o tempo gasto (R09 a medir na VM).

Sem --demo, gera a partir do banco configurado (DB_PATH).

Como rodar (a partir da raiz, com o venv ativo):
    python -m tia.agentes.relatorio --demo [--json] [--sem-llm]
    python -m tia.agentes.relatorio --aluno A2026-001 [--json] [--sem-llm]
    python -m tia.agentes.relatorio --turma [--perfil iniciante] [--json] [--sem-llm]

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL (opcional: sem ele, texto fixo na interpretação)
"""

import argparse
import json
import logging
import random
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import tia.core.database as database
from tia.agentes.planejador.modelos import EntradaPlanejador
from tia.agentes.planejador.planejar import gerar_trilha
from tia.agentes.planejador.repositorio import salvar_trilha
from tia.agentes.relatorio import gerar_relatorio_aluno, gerar_relatorio_turma
from tia.agentes.relatorio.narrativa import formatar_texto_aluno, formatar_texto_turma
from tia.agentes.tutor.repositorio import carregar_itens
from tia.core import auditoria
from tia.core.config import CHAT_MODEL

# (código, perfil, sessões [(competência, acertos "1"/"0", dias atrás, concluída)],
#  diálogos [(competência, dias atrás, vetada)]). Dados FICTÍCIOS.
ALUNOS_DEMO = [
    ("DEMO-R01", "iniciante", [("variaveis_tipos", "1111", 12, True), ("condicionais", "10111", 6, True),
                               ("repeticao", "11", 1, False)], [("repeticao", 1, False)]),
    ("DEMO-R02", "iniciante", [("variaveis_tipos", "11111", 10, True), ("condicionais", "1110", 5, False),
                               ("repeticao", "0100", 2, False)], []),
    ("DEMO-R03", "iniciante", [("variaveis_tipos", "1011", 14, False), ("variaveis_tipos", "110", 9, False)],
     [("variaveis_tipos", 9, False)]),
    ("DEMO-R04", "iniciante", [("variaveis_tipos", "1111", 8, True), ("repeticao", "010010", 3, False)],
     [("repeticao", 3, False), ("repeticao", 3, True), ("repeticao", 2, False)]),
    ("DEMO-R05", "intermediario", [("condicionais", "1111", 7, True), ("repeticao", "1101", 2, False)],
     [("funcoes", 2, False)]),
    ("DEMO-R06", "intermediario", [("funcoes", "0101", 4, False), ("repeticao", "10", 1, False)],
     [("funcoes", 4, True)]),
]
ALUNO_EXEMPLO = "DEMO-R02"  # o aluno em queda
SEM_ITEM_NEM_SESSAO = {"DEMO-R06"}  # simula respostas gravadas antes das colunas item_id/sessao_id


def popular_dados_sinteticos(agora: datetime, semente: int = 42):
    """Grava trilhas, sessões, respostas, diálogos e auditoria fictícios."""
    sorteio = random.Random(semente)
    itens_por_competencia: dict[str, list[str]] = {}
    for item in carregar_itens():
        itens_por_competencia.setdefault(item["competencia_id"], []).append(item["id"])
    for aluno_id, perfil_id, sessoes, dialogos in ALUNOS_DEMO:
        antigo = aluno_id in SEM_ITEM_NEM_SESSAO
        salvar_trilha(gerar_trilha(EntradaPlanejador(aluno_id=aluno_id, perfil_id=perfil_id, horas_semanais=6)), 6)
        conexao = database.obter_conexao()
        with conexao:
            for competencia, acertos, dias_atras, concluida in sessoes:
                inicio = agora - timedelta(days=dias_atras, hours=2)
                sessao_id = uuid.uuid4().hex
                itens = itens_por_competencia[competencia]
                nivel = 1
                for n, acerto in enumerate(acertos):
                    ts = (inicio + timedelta(minutes=3 * n)).isoformat(timespec="seconds")
                    cursor = conexao.execute(
                        """INSERT INTO historico_respostas (aluno_id, topico, acertou, timestamp, nivel, fontes, tempo_ms,
                                                           item_id, sessao_id)
                           VALUES (?, ?, ?, ?, ?, '[]', ?, ?, ?)""",
                        (aluno_id, competencia, acerto == "1", ts, nivel, sorteio.randint(4000, 60000),
                         None if antigo else itens[n % len(itens)], None if antigo else sessao_id))
                    origem = sorteio.choices(["LLM", "guarda", "fallback"], weights=[8, 1, 1])[0]
                    auditoria.registrar(conexao, aluno_id, "resposta_item", cursor.lastrowid, origem, [], ts=ts)
                    nivel = min(3, nivel + 1) if acerto == "1" else max(1, nivel - 1)
                fim = (inicio + timedelta(minutes=3 * len(acertos))).isoformat(timespec="seconds")
                conexao.execute(
                    """INSERT INTO tutor_sessoes (id, aluno_id, competencia_id, nivel, concluida, criado_em, atualizado_em)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (sessao_id, aluno_id, competencia, nivel, concluida, inicio.isoformat(timespec="seconds"), fim))
            for competencia, dias_atras, vetada in dialogos:
                ts = (agora - timedelta(days=dias_atras, hours=1)).isoformat(timespec="seconds")
                origem = sorteio.choice(["LLM", "LLM", "fallback"])
                cursor = conexao.execute(
                    """INSERT INTO tutor_dialogo (aluno_id, ts, competencia_id, pergunta, resposta, fontes, origem,
                                                  vetada, correcao_docente)
                       VALUES (?, ?, ?, 'pergunta fictícia', 'resposta fictícia', '[]', ?, ?, ?)""",
                    (aluno_id, ts, competencia, origem, vetada, "correção fictícia" if vetada else None))
                auditoria.registrar(conexao, aluno_id, "dialogo", cursor.lastrowid, origem, [], ts=ts)
        conexao.close()


def imprimir(relatorio, texto: str, segundos: float, como_json: bool):
    print(texto)
    if como_json:
        print("\nJSON:\n" + json.dumps(relatorio.model_dump(), ensure_ascii=False, indent=2))
    print(f"\n[tempo: {segundos:.2f} s | interpretação: {relatorio.narrativa.origem}]\n" + "-" * 78 + "\n")


def gerar_e_imprimir_aluno(aluno_id: str, agora: datetime | None, com_llm: bool, como_json: bool) -> float:
    inicio = time.perf_counter()
    relatorio = gerar_relatorio_aluno(aluno_id, agora=agora, com_narrativa=com_llm)
    segundos = time.perf_counter() - inicio
    if relatorio is None:
        print(f"Aluno {aluno_id} não encontrado.")
        return segundos
    imprimir(relatorio, formatar_texto_aluno(relatorio), segundos, como_json)
    return segundos


def gerar_e_imprimir_turma(perfil_id: str | None, agora: datetime | None, com_llm: bool, como_json: bool) -> float:
    inicio = time.perf_counter()
    relatorio = gerar_relatorio_turma(perfil_id, agora=agora, com_narrativa=com_llm)
    segundos = time.perf_counter() - inicio
    imprimir(relatorio, formatar_texto_turma(relatorio), segundos, como_json)
    return segundos


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Relatórios do Agente 3.")
    parser.add_argument("--demo", action="store_true", help="dados sintéticos em banco temporário")
    parser.add_argument("--aluno", help="código do aluno")
    parser.add_argument("--turma", action="store_true", help="relatório agregado")
    parser.add_argument("--perfil", help="com --turma: só este perfil")
    parser.add_argument("--json", action="store_true", help="imprime também o JSON")
    parser.add_argument("--sem-llm", action="store_true", help="não chama o LLM (texto fixo)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    com_llm = not args.sem_llm

    if args.demo:
        pasta = tempfile.mkdtemp(prefix="tia_relatorio_demo_")
        database.DB_PATH = str(Path(pasta) / "demo.db")
        database.criar_tabelas()
        agora = datetime.now().replace(microsecond=0)
        popular_dados_sinteticos(agora)
        print(f"\nBanco temporário: {database.DB_PATH} | {len(ALUNOS_DEMO)} alunos fictícios | "
              f"modelo {CHAT_MODEL}{' (sem LLM)' if args.sem_llm else ''}\n")
        tempos = [gerar_e_imprimir_aluno(ALUNO_EXEMPLO, agora, com_llm, args.json),
                  gerar_e_imprimir_turma(None, agora, com_llm, args.json),
                  gerar_e_imprimir_turma("iniciante", agora, com_llm, args.json)]
        print(f"Tempo: aluno {tempos[0]:.2f} s, instituição {tempos[1]:.2f} s, perfil iniciante {tempos[2]:.2f} s "
              f"(R09: até 15 s por interação, a medir na VM)")
    elif args.aluno:
        gerar_e_imprimir_aluno(args.aluno, None, com_llm, args.json)
    elif args.turma:
        gerar_e_imprimir_turma(args.perfil, None, com_llm, args.json)
    else:
        parser.print_help()
