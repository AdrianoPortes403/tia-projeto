"""
Pedidos sem login na auditoria, agregados (EAP 1.4.6, etapa 2).

Sem limite, cada pedido sem sessão (401) gravaria uma linha de auditoria, e
qualquer um poderia encher a auditoria. Aqui os pedidos são contados em
auth_anonimos por origem (IP), janela fixa de AUTH_ANONIMOS_JANELA_MINUTOS e
tipo (acesso_negado 401, login_bloqueado 429 e login_falha 401 de senha
errada, este desde a parte D4: senão muitos IPs diferentes gravariam uma
linha por tentativa):

- o PRIMEIRO pedido de cada origem na janela vai para a auditoria como antes
  (com a rota ou o login), desde que a janela ainda tenha menos de
  AUTH_ANONIMOS_MAX_ORIGENS origens registradas (contra muitos IPs);
- os demais só somam no contador;
- fechada a janela, uma linha "resumo_anonimos" por tipo grava o total de
  pedidos, de origens e quantos foram registrados um a um, se algum ficou só
  no contador. Nada se perde: a contagem completa vai para a auditoria.

O IP nunca vai para a auditoria; fica só em auth_anonimos e sai depois de
AUTH_RETENCAO_IP_DIAS (limpar).

Não é executável; usado por seguranca.acesso, tia.api.rotas_auth e
seguranca.limpeza.

Pré-requisitos:
    - tabelas criadas: python -m tia.core.database
"""

from datetime import datetime, timedelta

import tia.core.config as config
from tia.core import auditoria
from tia.core.database import obter_conexao


def _texto(momento: datetime) -> str:
    return momento.isoformat(timespec="seconds")


def inicio_da_janela(agora: datetime) -> datetime:
    """Começo da janela fixa que contém agora (contada a partir da meia-noite)."""
    tamanho = max(config.AUTH_ANONIMOS_JANELA_MINUTOS, 1)
    minutos = agora.hour * 60 + agora.minute
    meia_noite = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    return meia_noite + timedelta(minutes=minutos - minutos % tamanho)


def registrar(tipo: str, ip: str, referencia_id: str | None, origem: str, motivo: str,
              agora: datetime | None = None) -> bool:
    """Conta o pedido e grava a linha de auditoria se for o primeiro da origem
    na janela (e houver vaga). Devolve True se gravou na auditoria."""
    agora = agora or datetime.now()
    janela = inicio_da_janela(agora)
    fim = janela + timedelta(minutes=max(config.AUTH_ANONIMOS_JANELA_MINUTOS, 1))
    conexao = obter_conexao()
    try:
        with conexao:
            pedidos = conexao.execute(
                """INSERT INTO auth_anonimos (ip, janela, tipo, pedidos, primeiro_ts, ultimo_ts)
                   VALUES (?, ?, ?, 1, ?, ?)
                   ON CONFLICT (ip, janela, tipo) DO UPDATE SET pedidos = pedidos + 1, ultimo_ts = excluded.ultimo_ts
                   RETURNING pedidos""",
                (ip, _texto(janela), tipo, _texto(agora), _texto(agora))).fetchall()[0][0]
            if pedidos != 1:
                return False
            resumir(agora, conexao)  # nova origem: aproveita para resumir as janelas fechadas
            registradas = conexao.execute(
                "SELECT COUNT(*) FROM auth_anonimos WHERE janela = ? AND tipo = ? AND registrado",
                (_texto(janela), tipo)).fetchone()[0]
            if registradas >= config.AUTH_ANONIMOS_MAX_ORIGENS:
                return False
            conexao.execute("UPDATE auth_anonimos SET registrado = 1 WHERE ip = ? AND janela = ? AND tipo = ?",
                            (ip, _texto(janela), tipo))
            auditoria.registrar(conexao, None, tipo, referencia_id, origem, [], ts=_texto(agora),
                                motivo=f"{motivo}; outros pedidos desta origem até {fim:%H:%M} só são contados")
    finally:
        conexao.close()
    return True


def resumir(agora: datetime | None = None, conexao=None) -> int:
    """Grava o resumo das janelas já fechadas que tiveram pedidos só contados
    (uma linha "resumo_anonimos" por janela e tipo) e as marca como resumidas.
    Devolve quantos resumos gravou."""
    agora = agora or datetime.now()
    atual = _texto(inicio_da_janela(agora))
    propria = conexao is None
    conexao = conexao or obter_conexao()
    try:
        grupos = conexao.execute(
            """SELECT janela, tipo, SUM(pedidos) AS pedidos, COUNT(*) AS origens, SUM(registrado) AS registrados,
                      MIN(primeiro_ts) AS primeiro, MAX(ultimo_ts) AS ultimo
               FROM auth_anonimos WHERE janela < ? AND NOT resumido GROUP BY janela, tipo ORDER BY janela, tipo""",
            (atual,)).fetchall()
        resumos = 0
        for g in grupos:
            if g["pedidos"] > g["registrados"]:
                motivo = (f"{g['pedidos']} pedidos de {g['origens']} origem(ns) entre {g['primeiro'][11:16]} e "
                          f"{g['ultimo'][11:16]}; {g['registrados']} registrado(s) um a um, os demais só contados")
                if g["tipo"] == "login_falha":
                    motivo += f"; {_logins_na_janela(conexao, g['janela'])} login(s) diferente(s) tentado(s)"
                auditoria.registrar(conexao, None, "resumo_anonimos", f"janela:{g['janela']}", g["tipo"], [],
                                    ts=g["ultimo"], motivo=motivo)
                resumos += 1
            conexao.execute("UPDATE auth_anonimos SET resumido = 1 WHERE janela = ? AND tipo = ?",
                            (g["janela"], g["tipo"]))
        if propria:
            conexao.commit()
    finally:
        if propria:
            conexao.close()
    return resumos


def _logins_na_janela(conexao, janela: str) -> int:
    """Quantos logins diferentes falharam na janela (de auth_tentativas; só o número vai para a auditoria)."""
    inicio = datetime.fromisoformat(janela)
    fim = inicio + timedelta(minutes=max(config.AUTH_ANONIMOS_JANELA_MINUTOS, 1))
    return conexao.execute("SELECT COUNT(DISTINCT login) FROM auth_tentativas WHERE NOT sucesso AND ts >= ? AND ts < ?",
                           (janela, _texto(fim))).fetchone()[0]


def limpar(agora: datetime | None = None, conexao=None) -> int:
    """Resume o que faltar e apaga as contagens mais antigas que
    AUTH_RETENCAO_IP_DIAS (guardam o IP). Devolve quantas linhas saíram."""
    agora = agora or datetime.now()
    propria = conexao is None
    conexao = conexao or obter_conexao()
    try:
        resumir(agora, conexao)
        removidas = conexao.execute(
            "DELETE FROM auth_anonimos WHERE resumido AND janela < ?",
            (_texto(agora - timedelta(days=config.AUTH_RETENCAO_IP_DIAS)),)).rowcount
        if propria:
            conexao.commit()
    finally:
        if propria:
            conexao.close()
    return removidas
