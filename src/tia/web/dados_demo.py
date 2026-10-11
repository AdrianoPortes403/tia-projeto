"""
Dados fictícios para demonstrar a aplicação web standalone (EAP 1.4.4).

Cria, no banco configurado (DB_PATH, padrão data/tia.db), três alunos
fictícios pelo orquestrador (só códigos, nunca nomes, R08), todos no perfil
intermediário com o mesmo diagnóstico (trilha: Funções -> Listas e strings
-> Recursão):

    DEMO-W01  recém-matriculado: nada estudado
    DEMO-W02  concluiu Funções e respondeu 1 pergunta de Listas e strings
              (a tela Estudo continua a sessão aberta)
    DEMO-W03  concluiu Funções e caiu em Listas e strings: reforço de
              Repetição pendente (a tela Estudo abre a revisão)

Aluno que já existe no banco é mantido como está (rodar de novo não duplica).
Cria também os usuários FICTÍCIOS do login (1.4.6): o aluno DEMO-W01 e o
docente DEMO-DOCENTE, com a senha de demonstração (fictícia, pública,
impressa no fim; só para máquina de desenvolvimento).
Por padrão NÃO chama o Ollama (rápido: os agentes gravam os textos fixos,
origem "fallback"); com --com-llm, chama (pode levar vários minutos em CPU).
Imprime o tempo gasto.

Como rodar (a partir da raiz, com o venv ativo):
    python -m tia.web.dados_demo [--com-llm]
    uvicorn tia.api.main:app --reload    # e abrir http://localhost:8000/app/

Pré-requisitos:
    - pip install -e . (na raiz)
    - com --com-llm: Ollama rodando com CHAT_MODEL e EMBED_MODEL
"""

import argparse
import itertools
import logging
import time

import requests

import tia.core.llm_client as llm_client
from tia import orquestrador
from tia.agentes.tutor.repositorio import carregar_itens
from tia.core.config import DB_PATH
from tia.core.database import criar_tabelas
from tia.orquestrador.modelos import EventoTutor, Matricula
from tia.seguranca import usuarios

# PROVISÓRIO: diagnóstico fictício; o perfil intermediário dispensa variáveis, condicionais e repetição
MATRICULA = Matricula(perfil_id="intermediario", horas_semanais=6, diagnostico={
    "variaveis_tipos": 0.9, "condicionais": 0.8, "repeticao": 0.9,
    "funcoes": 0.2, "listas_strings": 0.2, "recursao": 0.0})
# aluno -> respostas em cada sessão aberta pelo orquestrador ("1" acerta, "0" erra)
ALUNOS = {
    "DEMO-W01": [],
    "DEMO-W02": ["1111", "1"],
    "DEMO-W03": ["1111", "000"],
}

contador = itertools.count(1)


def sem_llm():
    """Toda chamada ao Ollama (chat e embedding) falha na hora: os agentes usam os textos fixos."""
    def falha_imediata(*args, **kwargs):
        raise requests.ConnectionError("dados de demonstração sem LLM")
    llm_client.requests.post = falha_imediata


def estudar(aluno_id: str, sequencia: str, gabarito: dict[str, int]):
    """Abre a sessão indicada pelo orquestrador e responde a sequência."""
    proxima = orquestrador.proxima(aluno_id)
    aberta = orquestrador.abrir_sessao(aluno_id, proxima.competencia_id)
    sessao_id, pergunta = aberta.sessao.sessao_id, aberta.sessao.pergunta
    for c in sequencia:
        correto = gabarito[pergunta.item_id]
        resultado = orquestrador.processar_evento(aluno_id, EventoTutor(
            evento_id=f"demo-web-{aluno_id}-{time.time_ns()}-{next(contador)}", tipo="resposta",
            sessao_id=sessao_id, item_id=pergunta.item_id,
            indice_escolhido=correto if c == "1" else (correto + 1) % 4))
        for decisao in resultado.decisoes:
            print(f"   {aluno_id}: decisão [{decisao.regra}] {decisao.acao}")
        pergunta = resultado.feedback.proxima_pergunta
        if pergunta is None:
            break


def mostrar_usuarios_demonstracao():
    """Cria (se faltarem) os usuários FICTÍCIOS do login (1.4.6) e diz como entrar.
    A senha é a de demonstração, pública: só para máquina de desenvolvimento."""
    criados = usuarios.criar_usuarios_demonstracao()
    print(f"Usuários fictícios{' criados' if criados else ' (já existiam)'}: "
          + ", ".join(f"{i} ({papel})" for i, papel, _ in usuarios.USUARIOS_DEMONSTRACAO)
          + f". Senha FICTÍCIA de demonstração: {usuarios.SENHA_DEMONSTRACAO}")


def criar_alunos():
    criar_tabelas()
    gabarito = {i["id"]: i["indice_correto"] for i in carregar_itens()}
    for aluno_id, sessoes in ALUNOS.items():
        try:
            orquestrador.iniciar(aluno_id, MATRICULA)
        except orquestrador.JaMatriculado:
            print(f"{aluno_id}: já existe no banco; mantido como está.")
            continue
        for sequencia in sessoes:
            estudar(aluno_id, sequencia, gabarito)
        proxima = orquestrador.proxima(aluno_id)
        print(f"{aluno_id}: criado. Próxima ação: {proxima.acao} em '{proxima.competencia_id}'"
              f"{' (reforço)' if proxima.reforco else ''}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Alunos fictícios para a aplicação web standalone.")
    parser.add_argument("--com-llm", action="store_true", help="chama o Ollama (lento em CPU)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(name)s: %(message)s")
    if not args.com_llm:
        sem_llm()
    inicio = time.perf_counter()
    print(f"Banco: {DB_PATH}")
    criar_alunos()
    mostrar_usuarios_demonstracao()
    print(f"Tempo gasto: {time.perf_counter() - inicio:.1f} s")
    print("Suba a API (uvicorn tia.api.main:app --reload) e abra http://localhost:8000/app/")
