"""
Anonimização e cópia do banco (LGPD, EAP 1.4.6): peças comuns da retenção
(seguranca.retencao) e dos direitos do titular (seguranca.titular).

Anonimizar, aqui, é DESVINCULAR do aluno e APAGAR texto livre:
- aluno_id e as ligações que levam a ele (sessao_id, evento_id) viram NULL;
- textos livres (pergunta do diálogo, resposta, feedback, correção do
  docente) viram NULL;
- ficam só dados sem pessoa (item, competência, acerto, nível, data, origem
  do texto, veto), úteis para estatística por item, competência e origem.
Os indicadores do Agente 3 são calculados POR ALUNO: uma linha desvinculada
deixa de contar neles (docs/seguranca/lgpd.md).

Na auditoria (que nunca é apagada), anonimizar troca por "[anonimizado]" os
códigos de aluno e de usuário em aluno_id, usuario_id, referencia_id e motivo
(papel, tipo, data e origem ficam).

Cópia do banco: antes de aplicar a retenção ou eliminar os dados de um
titular, copiar_banco() faz uma cópia completa (API de backup do SQLite) em
COPIAS_DIR, com permissão só do dono. As cópias guardam os dados apagados e
saem depois de RETENCAO_COPIAS_DIAS (retencao).

Não é executável; usado por seguranca.retencao e seguranca.titular.

Pré-requisitos:
    - tabelas criadas: python -m tia.core.database
"""

import os
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import tia.core.config as config
import tia.core.database as database

ANONIMO = "[anonimizado]"
# tabelas com a coluna aluno_id (dados de estudo e de cadastro do aluno)
TABELAS_DO_ALUNO = ("trilha_estudo", "historico_respostas", "tutor_sessoes", "tutor_dialogo", "tutor_feedbacks",
                    "orquestrador_matriculas", "orquestrador_eventos", "orquestrador_decisoes",
                    "orquestrador_reforcos", "auditoria")
# textos livres: o que a anonimização apaga
TEXTOS_FEEDBACK = "explicacao = NULL, explicacao_descartada = NULL, correcao_docente = NULL"
TEM_TEXTO_FEEDBACK = "(explicacao IS NOT NULL OR explicacao_descartada IS NOT NULL OR correcao_docente IS NOT NULL)"
TEXTOS_DIALOGO = "pergunta = NULL, resposta = NULL, correcao_docente = NULL"
TEM_TEXTO_DIALOGO = "(pergunta IS NOT NULL OR resposta IS NOT NULL OR correcao_docente IS NOT NULL)"
# códigos muito curtos não são procurados dentro de textos (trocariam números comuns)
TAMANHO_MINIMO_NO_TEXTO = 4
_LOGIN = re.compile(r"login=[^;\s]*")
# segmento de rota com código de aluno ou de usuário (referência do acesso_negado)
_ROTA = re.compile(r"(/(?:aluno|alunos|auditoria|incentivo|usuarios)/)([^/?\s;]+)")


def codigos_conhecidos(conexao: sqlite3.Connection) -> set[str]:
    """Todos os códigos de aluno e de usuário que o banco conhece."""
    consultas = ["SELECT id FROM alunos", "SELECT id FROM usuarios", "SELECT aluno_id FROM usuarios",
                 "SELECT usuario_id FROM auditoria", "SELECT usuario_id FROM auth_sessoes",
                 "SELECT login FROM auth_tentativas"]
    consultas += [f"SELECT aluno_id FROM {tabela}" for tabela in TABELAS_DO_ALUNO]
    codigos = set()
    for sql in consultas:
        codigos.update(linha[0] for linha in conexao.execute(sql) if linha[0])
    return codigos


def padrao_de_codigos(codigos: set[str]) -> re.Pattern | None:
    longos = sorted((c for c in codigos if len(c) >= TAMANHO_MINIMO_NO_TEXTO), key=len, reverse=True)
    if not longos:
        return None
    return re.compile(r"(?<![A-Za-z0-9_-])(?:" + "|".join(map(re.escape, longos)) + r")(?![A-Za-z0-9_-])")


def limpar_texto(texto: str | None, padrao: re.Pattern | None, geral: bool) -> str | None:
    """Troca os códigos do padrão por [anonimizado]. geral: também todo login
    digitado (login=...) e todo código em rota, conhecido ou não."""
    if not texto:
        return texto
    if geral:
        texto = _LOGIN.sub("login=" + ANONIMO, texto)
        texto = _ROTA.sub(lambda m: m.group(1) + ANONIMO, texto)
    return padrao.sub(ANONIMO, texto) if padrao else texto


def anonimizar_auditoria(conexao: sqlite3.Connection, condicao: str, parametros: tuple, codigos: set[str],
                         geral: bool) -> int:
    """Anonimiza as linhas de auditoria que atendem à condição (SQL sobre a
    tabela auditoria). geral=True (retenção): apaga todo código de aluno e de
    usuário da linha e a marca como anonimizada. geral=False (titular): só os
    códigos dados (os de outras pessoas ficam, como o docente que vetou).
    Devolve quantas linhas mudaram."""
    padrao = padrao_de_codigos(codigos)
    linhas = conexao.execute(
        f"SELECT id, aluno_id, usuario_id, referencia_id, motivo FROM auditoria WHERE {condicao}", parametros
    ).fetchall()
    mudadas = 0
    for linha in linhas:
        novos = {
            "aluno_id": None if geral or linha["aluno_id"] in codigos else linha["aluno_id"],
            "usuario_id": None if geral or linha["usuario_id"] in codigos else linha["usuario_id"],
            "referencia_id": limpar_texto(linha["referencia_id"], padrao, geral),
            "motivo": limpar_texto(linha["motivo"], padrao, geral),
        }
        if not geral and all(novos[campo] == linha[campo] for campo in novos):
            continue
        conexao.execute(
            """UPDATE auditoria SET aluno_id = ?, usuario_id = ?, referencia_id = ?, motivo = ?,
                      anonimizada = CASE WHEN ? THEN 1 ELSE anonimizada END WHERE id = ?""",
            (novos["aluno_id"], novos["usuario_id"], novos["referencia_id"], novos["motivo"], int(geral),
             linha["id"]))
        mudadas += 1
    return mudadas


# --- cópias do banco ---

def pasta_das_copias() -> Path:
    return Path(config.COPIAS_DIR) if config.COPIAS_DIR else Path(database.DB_PATH).parent / "copias"


def copiar_banco(motivo: str, agora: datetime | None = None) -> Path:
    """Cópia completa do banco antes de uma operação que apaga dados. A pasta
    fica com permissão 700 e o arquivo com 600 (só o dono do serviço)."""
    pasta = pasta_das_copias()
    pasta.mkdir(parents=True, exist_ok=True)
    os.chmod(pasta, 0o700)
    destino = pasta / f"tia-{(agora or datetime.now()):%Y%m%d-%H%M%S-%f}-{motivo}.db"
    os.close(os.open(destino, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    origem, copia = sqlite3.connect(database.DB_PATH), sqlite3.connect(destino)
    try:
        origem.backup(copia)
    finally:
        copia.close()
        origem.close()
    return destino


def copias_vencidas(agora: datetime | None = None) -> list[Path]:
    """Cópias mais antigas que RETENCAO_COPIAS_DIAS."""
    pasta = pasta_das_copias()
    if not pasta.is_dir():
        return []
    limite = ((agora or datetime.now()) - timedelta(days=config.RETENCAO_COPIAS_DIAS)).timestamp()
    return sorted(c for c in pasta.glob("tia-*.db") if c.stat().st_mtime < limite)
