"""
Limpeza periódica das tabelas de segurança (EAP 1.4.6, etapa 2; retenção C1).

    auth_sessoes     sessões vencidas (limite absoluto ou inatividade)
    auth_tentativas  tentativas de login mais antigas que AUTH_RETENCAO_IP_DIAS
    auth_anonimos    contagens de pedidos sem login mais antigas que a retenção
                     (antes, as janelas fechadas são resumidas na auditoria)

As duas últimas guardam o IP, que nunca vai para a auditoria e fica no máximo
AUTH_RETENCAO_IP_DIAS (padrão 30, PROVISÓRIO). Cada limpeza que apaga algo
grava uma linha "limpeza_retencao" na auditoria, com as quantidades.

A API roda a limpeza ao subir e a cada AUTH_LIMPEZA_MINUTOS (tia.api.main).
Para rodar à mão ou por um agendador (cron, systemd timer), a partir da raiz,
com o venv ativo:
    python -m tia.seguranca.limpeza

Pré-requisitos:
    - tabelas criadas: python -m tia.core.database
"""

from datetime import datetime

from tia.core import auditoria
from tia.core.database import criar_tabelas, obter_conexao
from tia.seguranca import anonimos, sessoes


def limpar(agora: datetime | None = None) -> dict[str, int]:
    """Aplica a retenção numa transação; devolve quantas linhas saíram de cada tabela."""
    agora = agora or datetime.now()
    conexao = obter_conexao()
    try:
        with conexao:
            removidas = sessoes.limpar(agora, conexao)
            removidas["pedidos_sem_login"] = anonimos.limpar(agora, conexao)
            if any(removidas.values()):
                auditoria.registrar(conexao, None, "limpeza_retencao", None, "sistema", [],
                                    ts=agora.isoformat(timespec="seconds"),
                                    motivo="; ".join(f"{nome}={n}" for nome, n in removidas.items()))
    finally:
        conexao.close()
    return removidas


if __name__ == "__main__":
    criar_tabelas()
    resultado = limpar()
    print("Linhas apagadas: " + ", ".join(f"{nome} {n}" for nome, n in resultado.items()))
