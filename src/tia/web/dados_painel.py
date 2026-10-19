"""
Turma fictícia para demonstrar o painel do docente (EAP 1.4.5), sem LLM.

Cria, no banco configurado (DB_PATH, padrão data/tia.db), 12 alunos
fictícios DEMO-P01..DEMO-P12 (só códigos, nunca nomes, R08): 8 no perfil
intermediário e 4 no iniciante (abaixo do grupo mínimo de 5: o filtro por
perfil "iniciante" mostra o grupo suprimido). Situações variadas:

    ativos e indo bem, concluídos, inativos (5, 9 e 20 dias), em queda,
    com desempenho baixo, recém-matriculado sem atividade, e uma competência
    terminada sem domínio e sem acerto para avançar (DEMO-P06: concluída com
    ressalvas, recomeça a competência)

Regras do Tutor do 1.2.5 (15/10/2026): o nível das respostas segue os limiares
TUTOR_ACERTOS_SUBIR / TUTOR_ERROS_DESCER, e a sessão concluída grava com_ressalvas
e taxa_acerto como o Tutor grava. Na base comum (2 itens por nível) não há como
dominar (TUTOR_ACERTOS_CONCLUIR acertos seguidos no nível 3): toda sessão concluída
termina com ressalvas e só avança com acerto >= ORQ_ACERTO_MIN_AVANCO.

A matrícula passa pelo orquestrador (trilha do Planejador com o texto
padrão, decisão "planejar" na auditoria). As sessões, respostas e
diálogos são SINTÉTICOS, gravados direto no banco com datas no passado
(como em python -m tia.agentes.relatorio --demo): a origem dos feedbacks
(LLM/guarda/fallback) é sorteada; o texto do feedback (tutor_feedbacks) é a
explicação do item e, na origem "LLM", vem marcado "[demonstração]", como os
textos do diálogo. No fim, roda a verificação de inatividade do
orquestrador (R3), que registra as decisões de incentivo e de refazer a
trilha. Aluno que já existe é mantido (rodar de novo não duplica). Cria
também os usuários FICTÍCIOS do login (1.4.6): o docente DEMO-DOCENTE e o
aluno DEMO-W01, com a senha de demonstração impressa no fim.
Imprime o tempo gasto.

Como rodar (a partir da raiz, com o venv ativo):
    python -m tia.web.dados_painel
    uvicorn tia.api.main:app --reload    # e abrir http://localhost:8000/app/painel/

Pré-requisitos:
    - pip install -e . (na raiz)
    - nenhum Ollama: toda chamada ao LLM falha na hora (textos padrão)
"""

import json
import logging
import random
import time
import uuid
from datetime import datetime, timedelta

import tia.core.database as database
from tia import orquestrador
from tia.agentes.tutor import adaptativo
from tia.agentes.tutor.feedback import montar_veredito
from tia.agentes.tutor.repositorio import DIFICULDADE_POR_NIVEL, carregar_itens, materiais_da_competencia, vetar_dialogo
from tia.core import auditoria
from tia.orquestrador.modelos import Matricula
from tia.web.dados_demo import mostrar_usuarios_demonstracao, sem_llm

# PROVISÓRIO: diagnóstico fictício; no intermediário a trilha fica Funções -> Listas e strings -> Recursão
# notas na convenção do diagnóstico (1.2.5): 1 = dominado (sai da trilha), 1/3 = começa no nível 2
DIAGNOSTICO_INTERMEDIARIO = {"variaveis_tipos": 1.0, "condicionais": 1.0, "repeticao": 1.0,
                             "funcoes": 0.34, "listas_strings": 0.34, "recursao": 0.0}
MATRICULAS = {
    "intermediario": Matricula(perfil_id="intermediario", horas_semanais=6, diagnostico=DIAGNOSTICO_INTERMEDIARIO),
    "iniciante": Matricula(perfil_id="iniciante", horas_semanais=8, diagnostico={}),
}

# (código, perfil, dias desde a matrícula,
#  sessões [(competência, respostas "1" acerto / "0" erro, dias atrás, concluída)],
#  diálogos [(competência, dias atrás, índice em DIALOGOS)]). Dados FICTÍCIOS.
ALUNOS = [
    ("DEMO-P01", "intermediario", 15, [("funcoes", "1101111", 9, True), ("listas_strings", "11011", 1, False)],
     [("funcoes", 8, 0)]),
    ("DEMO-P02", "intermediario", 30, [("funcoes", "1101111", 25, True), ("listas_strings", "111111", 18, True),
                                       ("recursao", "1111", 12, True)], [("recursao", 13, 4)]),  # concluiu
    ("DEMO-P03", "intermediario", 14, [("funcoes", "1101111", 10, True), ("listas_strings", "1111", 4, False),
                                       ("listas_strings", "0100", 1, False)], [("listas_strings", 1, 1)]),  # queda
    ("DEMO-P04", "intermediario", 16, [("funcoes", "1101111", 13, True), ("listas_strings", "11011", 9, False)],
     []),                                                                                    # inativo 9 dias
    ("DEMO-P05", "intermediario", 26, [("funcoes", "10011", 20, False)], [("funcoes", 20, 2)]),  # inativo 20 dias
    ("DEMO-P06", "intermediario", 10, [("funcoes", "010010", 3, True), ("funcoes", "010", 1, False)],
     [("funcoes", 2, 2), ("funcoes", 1, 3)]),             # desempenho baixo; 1ª sessão sem domínio (33%)
    ("DEMO-P07", "intermediario", 8, [("funcoes", "1101111", 5, True), ("listas_strings", "111", 0, False)],
     [("listas_strings", 0, 5)]),
    ("DEMO-P08", "intermediario", 12, [("funcoes", "1111", 6, False), ("funcoes", "0000100", 1, False)],
     [("funcoes", 1, 6)]),                                                                   # queda + baixo
    ("DEMO-P09", "iniciante", 9, [("variaveis_tipos", "1111", 6, True), ("condicionais", "1111", 1, False)],
     [("condicionais", 1, 7)]),
    ("DEMO-P10", "iniciante", 1, [], []),                                                    # recém-matriculado
    ("DEMO-P11", "iniciante", 12, [("variaveis_tipos", "0101", 5, False)], []),              # inativo 5 dias
    ("DEMO-P12", "iniciante", 20, [("variaveis_tipos", "1111", 15, True), ("condicionais", "11111", 10, True),
                                   ("repeticao", "1111", 0, False)], [("repeticao", 0, 8)]),
]

# (pergunta, resposta, fonte, origem). Textos de EXEMPLO para a tela de revisão.
DIALOGOS = [
    ("Para que serve o return?", "[demonstração] O return encerra a função e devolve um valor para quem a chamou.",
     "funcoes.txt", "LLM"),
    ("Como pego o último elemento de uma lista?",
     "[demonstração] Use o índice -1: lista[-1] devolve o último elemento.", "listas_strings.txt", "LLM"),
    ("Uma função pode chamar outra?",
     "[demonstração] Sim. Trecho do material: \"uma função pode chamar outras funções\".",
     "funcoes.txt", "guarda"),
    ("Qual a diferença entre parâmetro e argumento?",
     "[demonstração] Parâmetro e argumento são a mesma coisa em Python.", "funcoes.txt", "LLM"),
    ("O que é caso base?", "[demonstração] É a condição em que a função recursiva para de chamar a si mesma.",
     "exemplo_recursao.txt", "LLM"),
    ("Como inverto uma string?", "[demonstração] O material não cobre esta pergunta. Procure o professor.",
     None, "fallback"),
    ("Variável local existe fora da função?",
     "[demonstração] Sim, a variável local continua existindo depois que a função termina.",
     "funcoes.txt", "LLM"),
    ("Quando uso elif?", "[demonstração] Use elif para testar outra condição quando a anterior for falsa.",
     "condicionais.txt", "LLM"),
    ("O que faz o range(3)?", "[demonstração] range(3) gera os números 0, 1 e 2.", "repeticao.txt", "LLM"),
]
# respostas de exemplo propositalmente erradas: a 6 já sai vetada (pela função do veto, R12);
# a 3 fica para o docente vetar na demonstração
VETADA = (6, "Errado: a variável local só existe enquanto a função executa. Revise o material de funções.")


def _ts(momento: datetime) -> str:
    return momento.isoformat(timespec="seconds")


def texto_feedback(item: dict, origem: str) -> tuple:
    """explicacao, origem, falha_llm, explicacao_descartada e motivo_descarte de
    exemplo (sem LLM): na origem "LLM", a explicação do item marcada como
    demonstração; nas outras, a explicação do item, como o Tutor faz de verdade."""
    if origem == "LLM":
        return "[demonstração] " + item["explicacao"], origem, None, None, None
    if origem == "guarda":
        return (item["explicacao"], origem, None, "[demonstração] Texto do LLM com um número que não está no item: 42.",
                "número fora do item: 42")
    return item["explicacao"], origem, "timeout", None, None


def gravar_atividade(aluno_id: str, sessoes: list, dialogos: list, agora: datetime, sorteio: random.Random,
                     itens: dict[str, list[dict]]):
    """Sessões, respostas (com auditoria) e diálogos sintéticos, com datas no passado."""
    vetados = []
    conexao = database.obter_conexao()
    try:
        with conexao:
            for competencia, respostas, dias_atras, concluida in sessoes:
                inicio = agora - timedelta(days=dias_atras, hours=3)
                sessao_id = uuid.uuid4().hex
                nivel, acertos, erros = 1, 0, 0
                for n, resposta in enumerate(respostas):
                    item = itens[competencia][n % len(itens[competencia])]
                    ts = _ts(inicio + timedelta(minutes=4 * n))
                    origem = sorteio.choices(["LLM", "guarda", "fallback"], weights=[7, 2, 1])[0]
                    # como no Tutor: só a explicação do LLM cita fonte; guarda e fallback usam o texto do item
                    fontes = (materiais_da_competencia(competencia) or [])[:1] if origem == "LLM" else []
                    cursor = conexao.execute(
                        """INSERT INTO historico_respostas (aluno_id, topico, dificuldade, acertou, timestamp, nivel,
                                                            fontes, tempo_ms, item_id, sessao_id)
                           VALUES (?, ?, ?, ?, ?, ?, '[]', ?, ?, ?)""",
                        (aluno_id, competencia, DIFICULDADE_POR_NIVEL[nivel], resposta == "1", ts, nivel,
                         sorteio.randint(4000, 60000), item["id"], sessao_id))
                    resposta_id = cursor.lastrowid
                    indice = item["indice_correto"] if resposta == "1" else (item["indice_correto"] + 1) % 4
                    conexao.execute(
                        """INSERT INTO tutor_feedbacks (resposta_id, aluno_id, sessao_id, item_id, competencia_id, ts,
                                                        veredito, explicacao, origem, falha_llm,
                                                        explicacao_descartada, motivo_descarte, fontes)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (resposta_id, aluno_id, sessao_id, item["id"], competencia, ts,
                         montar_veredito(item, indice), *texto_feedback(item, origem), json.dumps(fontes)))
                    auditoria.registrar(conexao, aluno_id, "resposta_item", resposta_id, origem, fontes, ts=ts)
                    # regras do 1.2.5: sequências de acertos sobem e de erros descem um nível
                    if resposta == "1":
                        acertos, erros = acertos + 1, 0
                        if acertos >= adaptativo.acertos_para_subir() and nivel < 3:
                            nivel, acertos = nivel + 1, 0
                    else:
                        acertos, erros = 0, erros + 1
                        if erros >= adaptativo.erros_para_descer():
                            nivel, erros = max(1, nivel - 1), 0
                # sessão concluída: como o Tutor grava. Sem itens para o domínio (base comum), com ressalvas
                por_nivel = [sum(i["nivel"] == n for i in itens[competencia]) for n in (1, 2, 3)]
                dominavel = (min(por_nivel[:2]) >= adaptativo.acertos_para_subir()
                             and por_nivel[2] >= adaptativo.acertos_para_concluir())
                com_ressalvas = (not dominavel) if concluida else None
                taxa = round(respostas.count("1") / len(respostas), 3) if concluida else None
                conexao.execute(
                    """INSERT INTO tutor_sessoes (id, aluno_id, competencia_id, nivel, item_atual_id, itens_usados,
                                                  acertos_seguidos_nivel_max, concluida, criado_em, atualizado_em,
                                                  com_ressalvas, taxa_acerto)
                       VALUES (?, ?, ?, ?, NULL, '[]', 0, ?, ?, ?, ?, ?)""",
                    (sessao_id, aluno_id, competencia, nivel, concluida, _ts(inicio),
                     _ts(inicio + timedelta(minutes=4 * len(respostas))), com_ressalvas, taxa))
            for competencia, dias_atras, indice in dialogos:
                pergunta, resposta, fonte, origem = DIALOGOS[indice]
                ts = _ts(agora - timedelta(days=dias_atras, hours=2))
                fontes = [fonte] if fonte else []
                cursor = conexao.execute(
                    """INSERT INTO tutor_dialogo (aluno_id, ts, competencia_id, pergunta, resposta, fontes, origem,
                                                  tempo_ms)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (aluno_id, ts, competencia, pergunta, resposta, json.dumps(fontes), origem,
                     sorteio.randint(8000, 70000)))
                auditoria.registrar(conexao, aluno_id, "dialogo", cursor.lastrowid, origem, fontes, ts=ts)
                if indice == VETADA[0]:
                    vetados.append(cursor.lastrowid)
    finally:
        conexao.close()
    for dialogo_id in vetados:
        vetar_dialogo(dialogo_id, True, VETADA[1])


def recuar_matricula(aluno_id: str, quando: datetime):
    """A trilha e a matrícula recém-gravadas passam a ter a data da matrícula fictícia."""
    conexao = database.obter_conexao()
    try:
        with conexao:
            conexao.execute("UPDATE trilha_estudo SET criado_em = ? WHERE aluno_id = ?", (_ts(quando), aluno_id))
            conexao.execute("UPDATE orquestrador_matriculas SET criado_em = ?, atualizado_em = ? WHERE aluno_id = ?",
                            (_ts(quando), _ts(quando), aluno_id))
    finally:
        conexao.close()


def criar_turma(agora: datetime | None = None, semente: int = 7) -> list[str]:
    """Cria os alunos que ainda não existem; devolve os códigos criados."""
    agora = agora or datetime.now()
    database.criar_tabelas()
    sorteio = random.Random(semente)
    itens: dict[str, list[dict]] = {}
    for item in sorted(carregar_itens(), key=lambda i: (i["nivel"], i["id"])):
        itens.setdefault(item["competencia_id"], []).append(item)
    criados = []
    for aluno_id, perfil, dias_matricula, sessoes, dialogos in ALUNOS:
        matriculado_em = agora - timedelta(days=dias_matricula)
        try:
            orquestrador.iniciar(aluno_id, MATRICULAS[perfil], agora=matriculado_em)
        except orquestrador.JaMatriculado:
            print(f"{aluno_id}: já existe no banco; mantido como está.")
            continue
        recuar_matricula(aluno_id, matriculado_em)
        gravar_atividade(aluno_id, sessoes, dialogos, agora, sorteio, itens)
        criados.append(aluno_id)
        print(f"{aluno_id}: criado ({perfil}, {len(sessoes)} sessão(ões), {len(dialogos)} pergunta(s) ao tutor).")
    if criados:
        verificacao = orquestrador.verificar_inatividade(agora)
        acoes = [d.decisao.acao for d in verificacao.decisoes if d.aluno_id in criados]
        print(f"Verificação de inatividade (R3): {acoes.count('incentivar')} incentivo(s), "
              f"{acoes.count('refazer_trilha')} trilha(s) refeita(s).")
    return criados


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(name)s: %(message)s")
    sem_llm()
    inicio = time.perf_counter()
    print(f"Banco: {database.DB_PATH}")
    criar_turma()
    mostrar_usuarios_demonstracao()
    print(f"Tempo gasto: {time.perf_counter() - inicio:.1f} s")
    print("Suba a API (uvicorn tia.api.main:app --reload) e abra http://localhost:8000/app/painel/")
