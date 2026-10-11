"""
Retenção dos dados pessoais (LGPD, EAP 1.4.6, C1): anonimiza ou apaga o que
passou do prazo. Prazos em core/config.py (PROVISÓRIOS, a validar com o
jurídico/DEP), contados da data de cada registro:

    RETENCAO_FEEDBACK_TEXTO_DIAS  textos do feedback das questões apagados; resultado
                                  guardado dos eventos (que repete o feedback) apagado
    RETENCAO_DIALOGO_DIAS         diálogo livre: textos apagados, linha desvinculada
    RETENCAO_RESPOSTAS_DIAS       respostas, feedbacks, sessões, decisões e reforços
                                  desvinculados do aluno
    RETENCAO_AUDITORIA_DIAS       auditoria NÃO é apagada: só os códigos de aluno e de
                                  usuário dela são anonimizados
    AUTH_RETENCAO_IP_DIAS         sessões vencidas, tentativas de login e pedidos sem
                                  login (seguranca.limpeza, reaproveitada aqui)
    RETENCAO_COPIAS_DIAS          cópias do banco feitas antes de apagar dados

Cadastro, matrícula e trilha não têm prazo por data: ficam enquanto o aluno
estuda e saem pela eliminação a pedido (seguranca.titular). O que conta como
anonimizar: seguranca.anonimizacao.

--simular executa tudo numa transação e a DESFAZ: nada muda, e a saída lista
quantas linhas de cada tabela seriam afetadas e quais cópias sairiam.
--aplicar faz antes uma cópia do banco (se houver algo a fazer), aplica numa
transação só e grava uma linha "retencao" na auditoria com as quantidades.

Como rodar (a partir da raiz, com o venv ativo; agendar o --aplicar no cron):
    python -m tia.seguranca.retencao --simular
    python -m tia.seguranca.retencao --aplicar

Pré-requisitos:
    - tabelas criadas: python -m tia.core.database
"""

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import tia.core.config as config
from tia.core import auditoria
from tia.core.database import criar_tabelas, obter_conexao
from tia.seguranca import anonimizacao, limpeza
from tia.seguranca.anonimizacao import TEM_TEXTO_DIALOGO, TEM_TEXTO_FEEDBACK, TEXTOS_DIALOGO, TEXTOS_FEEDBACK


@dataclass
class Operacao:
    descricao: str
    tabela: str
    acao: str                # "anonimizar" (UPDATE ... SET) ou "apagar" (DELETE)
    prazo: str               # nome da configuração do prazo
    condicao: str            # SQL com um "?" para a data limite
    atribuicoes: str = ""    # SET do "anonimizar"
    linhas: int = 0
    limite: str = ""


@dataclass
class Resultado:
    simulacao: bool
    agora: str
    operacoes: list[Operacao]
    auditoria_anonimizada: int
    limpeza: dict[str, int]
    copias_vencidas: list[Path]
    copia_feita: Path | None = None
    total: int = field(init=False)

    def __post_init__(self):
        self.total = (sum(o.linhas for o in self.operacoes) + self.auditoria_anonimizada
                      + sum(self.limpeza.values()) + len(self.copias_vencidas))


def operacoes() -> list[Operacao]:
    """O que a retenção faz, na ordem (todas idempotentes: só pegam o que ainda tem dado pessoal)."""
    desvincular = "aluno_id IS NOT NULL"
    return [
        Operacao("textos do feedback das questões", "tutor_feedbacks", "anonimizar", "RETENCAO_FEEDBACK_TEXTO_DIAS",
                 f"ts < ? AND {TEM_TEXTO_FEEDBACK}", TEXTOS_FEEDBACK),
        Operacao("resultado guardado dos eventos (repete o feedback)", "orquestrador_eventos", "apagar",
                 "RETENCAO_FEEDBACK_TEXTO_DIAS", "recebido_em < ?"),
        Operacao("diálogo livre (pergunta, resposta e correção)", "tutor_dialogo", "anonimizar",
                 "RETENCAO_DIALOGO_DIAS", f"ts < ? AND ({desvincular} OR {TEM_TEXTO_DIALOGO})",
                 "aluno_id = NULL, " + TEXTOS_DIALOGO),
        Operacao("respostas do questionário", "historico_respostas", "anonimizar", "RETENCAO_RESPOSTAS_DIAS",
                 f"timestamp < ? AND {desvincular}", "aluno_id = NULL, sessao_id = NULL"),
        Operacao("feedback das questões (ligação com o aluno)", "tutor_feedbacks", "anonimizar",
                 "RETENCAO_RESPOSTAS_DIAS", f"ts < ? AND {desvincular}", "aluno_id = NULL, sessao_id = NULL"),
        Operacao("sessões do questionário", "tutor_sessoes", "anonimizar", "RETENCAO_RESPOSTAS_DIAS",
                 f"COALESCE(atualizado_em, criado_em) < ? AND {desvincular}", "aluno_id = NULL"),
        Operacao("decisões do orquestrador", "orquestrador_decisoes", "anonimizar", "RETENCAO_RESPOSTAS_DIAS",
                 f"ts < ? AND {desvincular}", "aluno_id = NULL, evento_id = NULL, sessao_id = NULL"),
        Operacao("reforços do orquestrador", "orquestrador_reforcos", "anonimizar", "RETENCAO_RESPOSTAS_DIAS",
                 f"COALESCE(concluido_em, criado_em) < ? AND {desvincular}",
                 "aluno_id = NULL, sessao_original_id = NULL, sessao_reforco_id = NULL"),
    ]


def _limite(agora: datetime, prazo: str) -> str:
    return (agora - timedelta(days=getattr(config, prazo))).isoformat(timespec="seconds")


def _executar(conexao, agora: datetime) -> tuple[list[Operacao], int, dict[str, int]]:
    codigos = anonimizacao.codigos_conhecidos(conexao)  # antes de desvincular qualquer coisa
    feitas = []
    for operacao in operacoes():
        operacao.limite = _limite(agora, operacao.prazo)
        if operacao.acao == "apagar":
            sql = f"DELETE FROM {operacao.tabela} WHERE {operacao.condicao}"
        else:
            sql = f"UPDATE {operacao.tabela} SET {operacao.atribuicoes} WHERE {operacao.condicao}"
        operacao.linhas = conexao.execute(sql, (operacao.limite,)).rowcount
        feitas.append(operacao)
    auditoria_anonimizada = anonimizacao.anonimizar_auditoria(
        conexao, "ts < ? AND NOT anonimizada", (_limite(agora, "RETENCAO_AUDITORIA_DIAS"),), codigos, geral=True)
    return feitas, auditoria_anonimizada, limpeza.aplicar(conexao, agora)


def _simular(agora: datetime) -> Resultado:
    conexao = obter_conexao()
    try:
        feitas, anonimizadas, limpas = _executar(conexao, agora)
        conexao.rollback()  # simulação: desfaz tudo
    finally:
        conexao.close()
    return Resultado(True, agora.isoformat(timespec="seconds"), feitas, anonimizadas, limpas,
                     anonimizacao.copias_vencidas(agora))


def executar(simular: bool = True, agora: datetime | None = None) -> Resultado:
    """Simula (padrão) ou aplica a retenção. Ao aplicar, só copia o banco e
    mexe nele se a simulação achar algo a fazer."""
    agora = agora or datetime.now()
    previa = _simular(agora)
    if simular:
        return previa
    vencidas = previa.copias_vencidas
    if previa.total == len(vencidas):  # nada no banco: no máximo, cópias vencidas
        for copia in vencidas:
            copia.unlink()
        if vencidas:
            conexao = obter_conexao()
            try:
                with conexao:
                    auditoria.registrar(conexao, None, "retencao", None, "sistema", [],
                                        ts=agora.isoformat(timespec="seconds"),
                                        motivo=f"cópias apagadas={len(vencidas)}")
            finally:
                conexao.close()
        return Resultado(False, previa.agora, previa.operacoes, 0, previa.limpeza, vencidas)
    copia = anonimizacao.copiar_banco("retencao", agora)
    conexao = obter_conexao()
    try:
        with conexao:
            feitas, anonimizadas, limpas = _executar(conexao, agora)
            partes = [f"{o.tabela}.{o.acao}={o.linhas}" for o in feitas if o.linhas]
            partes += [f"auditoria.anonimizada={anonimizadas}"] + [f"{k}={v}" for k, v in limpas.items() if v]
            partes.append(f"cópias apagadas={len(vencidas)}; cópia prévia {copia.name}")
            auditoria.registrar(conexao, None, "retencao", None, "sistema", [],
                                ts=agora.isoformat(timespec="seconds"), motivo="; ".join(partes))
    finally:
        conexao.close()
    for vencida in vencidas:
        vencida.unlink()
    return Resultado(False, previa.agora, feitas, anonimizadas, limpas, vencidas, copia)


def relatorio(resultado: Resultado) -> str:
    """Texto para o terminal: quantidades, sem nenhum dado pessoal."""
    titulo = "SIMULAÇÃO (nada foi alterado)" if resultado.simulacao else "RETENÇÃO APLICADA"
    linhas = [f"{titulo} em {resultado.agora}"]
    for o in resultado.operacoes:
        verbo = "apagada(s)" if o.acao == "apagar" else "anonimizada(s)"
        linhas.append(f"- {o.descricao} [{o.tabela}]: {o.linhas} linha(s) {verbo} "
                      f"({o.prazo}={getattr(config, o.prazo)}; registros antes de {o.limite})")
    linhas.append(f"- auditoria: {resultado.auditoria_anonimizada} linha(s) com códigos anonimizados "
                  f"(RETENCAO_AUDITORIA_DIAS={config.RETENCAO_AUDITORIA_DIAS}; a auditoria nunca é apagada)")
    linhas.append(f"- sessões vencidas: {resultado.limpeza['sessoes']}; tentativas de login: "
                  f"{resultado.limpeza['tentativas']}; pedidos sem login: {resultado.limpeza['pedidos_sem_login']} "
                  f"(AUTH_RETENCAO_IP_DIAS={config.AUTH_RETENCAO_IP_DIAS})")
    linhas.append(f"- cópias do banco vencidas (RETENCAO_COPIAS_DIAS={config.RETENCAO_COPIAS_DIAS}): "
                  + (", ".join(c.name for c in resultado.copias_vencidas) or "nenhuma"))
    if resultado.copia_feita:
        linhas.append(f"Cópia do banco antes de aplicar: {resultado.copia_feita}")
    linhas.append(f"Total: {resultado.total}")
    return "\n".join(linhas)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retenção dos dados pessoais (LGPD).")
    modo = parser.add_mutually_exclusive_group(required=True)
    modo.add_argument("--simular", action="store_true", help="lista o que seria afetado, sem alterar nada")
    modo.add_argument("--aplicar", action="store_true", help="copia o banco e aplica os prazos")
    args = parser.parse_args()
    criar_tabelas()
    print(relatorio(executar(simular=args.simular)))
