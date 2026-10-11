"""
Direitos do titular (LGPD, EAP 1.4.6, C2): exportar e eliminar os dados de um
aluno. Feito no servidor por quem administra o TIA, a pedido do aluno (o
canal do pedido é da instituição: docs/seguranca/lgpd.md).

exportar: JSON com TODOS os dados do aluno (cadastro, usuário sem a senha,
matrícula, trilha, respostas, sessões, diálogo, feedbacks, decisões,
reforços, eventos, auditoria, tentativas de login sem IP), sem dados de
outras pessoas: códigos de outros alunos e usuários que aparecem nos
registros dele viram "[anonimizado]". O arquivo é criado com permissão só do
dono e não sobrescreve outro. A exportação vai para a auditoria.

eliminar: pede confirmação explícita (digitar o código de novo, ou
--confirmar CODIGO), faz uma cópia do banco e, numa transação só:
- apaga cadastro, matrícula, trilha, sessões, reforços e eventos do aluno;
- desvincula e apaga os textos de respostas, feedbacks, diálogo e decisões
  (ficam linhas sem pessoa, para estatística; seguranca.anonimizacao);
- anonimiza os códigos dele na auditoria, que não é apagada;
- desativa o(s) usuário(s) ligado(s) ao aluno (senha inutilizada, sessões
  e tentativas de login apagadas). O id de login fica, desativado, para não
  ser reaproveitado;
- grava "direito_titular" na auditoria SEM o código, com um número de
  protocolo para responder ao titular.

Como rodar (a partir da raiz, com o venv ativo):
    python -m tia.seguranca.titular exportar --aluno A2026-001 [--saida arquivo.json]
    python -m tia.seguranca.titular eliminar --aluno A2026-001

Pré-requisitos:
    - tabelas criadas: python -m tia.core.database
"""

import argparse
import json
import os
import secrets
import sys
from datetime import datetime
from pathlib import Path

from tia.core import auditoria
from tia.core.database import criar_tabelas, obter_conexao
from tia.seguranca import anonimizacao
from tia.seguranca.anonimizacao import ANONIMO, TEXTOS_DIALOGO, TEXTOS_FEEDBACK
from tia.seguranca.usuarios import PADRAO_ID

# o que sai de cada tabela na eliminação
APAGAR = ("trilha_estudo", "orquestrador_matriculas", "orquestrador_reforcos", "orquestrador_eventos",
          "tutor_sessoes")
DESVINCULAR = {
    "historico_respostas": "aluno_id = NULL, sessao_id = NULL",
    "tutor_feedbacks": "aluno_id = NULL, sessao_id = NULL, " + TEXTOS_FEEDBACK,
    "tutor_dialogo": "aluno_id = NULL, " + TEXTOS_DIALOGO,
    "orquestrador_decisoes": "aluno_id = NULL, evento_id = NULL, sessao_id = NULL",
}
SENHA_INUTILIZADA = "eliminado"  # não é um hash válido: nenhuma senha confere


class ErroTitular(ValueError):
    """Pedido inválido (mensagem pensada para quem opera o comando)."""


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _validar(aluno_id: str):
    if not PADRAO_ID.match(aluno_id or ""):
        raise ErroTitular("Código de aluno inválido.")


def _usuarios_do_aluno(conexao, aluno_id: str) -> list[str]:
    return [l["id"] for l in conexao.execute("SELECT id FROM usuarios WHERE aluno_id = ? ORDER BY id", (aluno_id,))]


def _existe(conexao, aluno_id: str) -> bool:
    if _usuarios_do_aluno(conexao, aluno_id):
        return True
    if conexao.execute("SELECT 1 FROM alunos WHERE id = ?", (aluno_id,)).fetchone():
        return True
    return any(conexao.execute(f"SELECT 1 FROM {t} WHERE aluno_id = ? LIMIT 1", (aluno_id,)).fetchone()
               for t in anonimizacao.TABELAS_DO_ALUNO)


# --- exportar ---

def _linhas(conexao, sql: str, parametros: tuple) -> list[dict]:
    return [dict(l) for l in conexao.execute(sql, parametros).fetchall()]


def exportar(aluno_id: str) -> dict:
    """Todos os dados do aluno, sem dados de outras pessoas. Grava
    "direito_titular" (exportação) na auditoria."""
    _validar(aluno_id)
    conexao = obter_conexao()
    try:
        if not _existe(conexao, aluno_id):
            raise ErroTitular("Nenhum dado encontrado para esse código de aluno.")
        proprios = {aluno_id, *_usuarios_do_aluno(conexao, aluno_id)}
        padrao_outros = anonimizacao.padrao_de_codigos(anonimizacao.codigos_conhecidos(conexao) - proprios)
        marcas = ",".join("?" * len(proprios))

        def por_aluno(tabela: str, ordem: str) -> list[dict]:
            return _linhas(conexao, f"SELECT * FROM {tabela} WHERE aluno_id = ? ORDER BY {ordem}", (aluno_id,))

        eventos = por_aluno("orquestrador_eventos", "recebido_em")
        for evento in eventos:
            evento["resultado"] = json.loads(evento["resultado"]) if evento["resultado"] else None
        registros = []
        for linha in _linhas(conexao, f"""SELECT * FROM auditoria WHERE aluno_id = ? OR usuario_id IN ({marcas})
                                          ORDER BY ts, id""", (aluno_id, *proprios)):
            # nos registros dele, quem agiu por outra pessoa (docente, outro aluno) aparece só pelo papel
            linha["aluno_id"] = linha["aluno_id"] if linha["aluno_id"] in proprios or not linha["aluno_id"] else ANONIMO
            linha["usuario_id"] = linha["usuario_id"] if linha["usuario_id"] in proprios or not linha["usuario_id"] \
                else ANONIMO
            for campo in ("referencia_id", "motivo"):
                linha[campo] = anonimizacao.limpar_texto(linha[campo], padrao_outros, geral=False)
            linha["fontes"] = json.loads(linha["fontes"] or "[]")
            registros.append(linha)
        # consultas do painel que mostraram o código dele (o texto lista outros alunos: só data, tipo e papel)
        so_ele = anonimizacao.padrao_de_codigos({aluno_id})
        consultas = [
            {"ts": l["ts"], "tipo": l["tipo"], "referencia_id": l["referencia_id"], "usuario_papel": l["usuario_papel"]}
            for l in _linhas(conexao, """SELECT * FROM auditoria WHERE tipo = 'consulta_painel' AND motivo LIKE ?
                                         ORDER BY ts, id""", (f"%{aluno_id}%",))
            if so_ele is None or so_ele.search(l["motivo"] or "")]
        dados = {
            "titular": {"aluno_id": aluno_id},
            "gerado_em": _agora(),
            "aviso": ("Dados pessoais de um único aluno, exportados a pedido do titular (LGPD, art. 18). Entregue "
                      "por canal seguro e apague esta cópia depois da entrega."),
            "usuarios": _linhas(conexao, """SELECT id, papel, aluno_id, ativo, trocar_senha, criado_em, atualizado_em
                                            FROM usuarios WHERE aluno_id = ? ORDER BY id""", (aluno_id,)),
            "alunos": _linhas(conexao, "SELECT * FROM alunos WHERE id = ?", (aluno_id,)),
            "matricula": por_aluno("orquestrador_matriculas", "aluno_id"),
            "trilha_estudo": por_aluno("trilha_estudo", "id"),
            "respostas": por_aluno("historico_respostas", "id"),
            "sessoes_do_questionario": por_aluno("tutor_sessoes", "criado_em"),
            "feedbacks_das_questoes": por_aluno("tutor_feedbacks", "resposta_id"),
            "dialogo": por_aluno("tutor_dialogo", "id"),
            "decisoes_do_orquestrador": por_aluno("orquestrador_decisoes", "id"),
            "reforcos": por_aluno("orquestrador_reforcos", "id"),
            "eventos": eventos,
            "auditoria": registros,
            "consultas_do_painel_que_mostraram_o_aluno": consultas,
            # sem IP: o endereço de uma tentativa pode ser de outra pessoa
            "tentativas_de_login": _linhas(conexao, f"""SELECT ts, sucesso FROM auth_tentativas
                                                        WHERE login IN ({marcas}) ORDER BY ts""", tuple(proprios)),
            "sessoes_abertas": conexao.execute(f"SELECT COUNT(*) FROM auth_sessoes WHERE usuario_id IN ({marcas})",
                                               tuple(proprios)).fetchone()[0],
        }
        total = sum(len(v) for v in dados.values() if isinstance(v, list))
        with conexao:
            auditoria.registrar(conexao, aluno_id, "direito_titular", "exportacao", "comando", [], ts=_agora(),
                                motivo=f"dados exportados a pedido do titular ({total} registros)")
    finally:
        conexao.close()
    return dados


def gravar_exportacao(dados: dict, saida: Path) -> Path:
    """Grava o JSON com permissão só do dono; nunca sobrescreve."""
    descritor = os.open(saida, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descritor, "w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)
    return saida


# --- eliminar ---

def eliminar(aluno_id: str, confirmacao: str) -> dict:
    """Elimina os dados do aluno (ver o topo do módulo). confirmacao precisa
    ser o mesmo código. Devolve o resumo, com o protocolo e a cópia feita."""
    _validar(aluno_id)
    if confirmacao != aluno_id:
        raise ErroTitular("Confirmação não confere: nada foi alterado.")
    conexao = obter_conexao()
    try:
        if not _existe(conexao, aluno_id):
            raise ErroTitular("Nenhum dado encontrado para esse código de aluno.")
    finally:
        conexao.close()
    copia = anonimizacao.copiar_banco("eliminacao")
    protocolo = "titular-" + secrets.token_hex(4)
    resumo = {"protocolo": protocolo, "copia": str(copia), "apagadas": {}, "desvinculadas": {}}
    conexao = obter_conexao()
    try:
        with conexao:
            usuarios_ids = _usuarios_do_aluno(conexao, aluno_id)
            proprios = {aluno_id, *usuarios_ids}
            marcas = ",".join("?" * len(proprios))
            for tabela, atribuicoes in DESVINCULAR.items():
                resumo["desvinculadas"][tabela] = conexao.execute(
                    f"UPDATE {tabela} SET {atribuicoes} WHERE aluno_id = ?", (aluno_id,)).rowcount
            for tabela in APAGAR:
                resumo["apagadas"][tabela] = conexao.execute(
                    f"DELETE FROM {tabela} WHERE aluno_id = ?", (aluno_id,)).rowcount
            resumo["apagadas"]["alunos"] = conexao.execute("DELETE FROM alunos WHERE id = ?", (aluno_id,)).rowcount
            resumo["apagadas"]["auth_sessoes"] = conexao.execute(
                f"DELETE FROM auth_sessoes WHERE usuario_id IN ({marcas})", tuple(proprios)).rowcount
            resumo["apagadas"]["auth_tentativas"] = conexao.execute(
                f"DELETE FROM auth_tentativas WHERE login IN ({marcas})", tuple(proprios)).rowcount
            resumo["usuarios_desativados"] = conexao.execute(
                """UPDATE usuarios SET ativo = 0, aluno_id = NULL, senha_hash = ?, trocar_senha = 0, atualizado_em = ?
                   WHERE aluno_id = ?""", (SENHA_INUTILIZADA, _agora(), aluno_id)).rowcount
            condicoes = ["aluno_id IN ({0})", "usuario_id IN ({0})"]
            parametros = [*proprios, *proprios]
            for codigo in proprios:
                condicoes += ["referencia_id LIKE ?", "motivo LIKE ?"]
                parametros += [f"%{codigo}%", f"%{codigo}%"]
            resumo["auditoria_anonimizada"] = anonimizacao.anonimizar_auditoria(
                conexao, " OR ".join(c.format(marcas) for c in condicoes), tuple(parametros), proprios, geral=False)
            partes = [f"{t} apagadas={n}" for t, n in resumo["apagadas"].items() if n]
            partes += [f"{t} desvinculadas={n}" for t, n in resumo["desvinculadas"].items() if n]
            partes += [f"auditoria anonimizada={resumo['auditoria_anonimizada']}",
                       f"usuários desativados={resumo['usuarios_desativados']}", f"cópia prévia {copia.name}"]
            # sem o código do aluno: o protocolo liga este registro ao pedido
            auditoria.registrar(conexao, None, "direito_titular", protocolo, "comando", [], ts=_agora(),
                                motivo="eliminação a pedido do titular; " + "; ".join(partes))
    finally:
        conexao.close()
    return resumo


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Direitos do titular (LGPD): exportar ou eliminar os dados de um aluno.")
    comandos = parser.add_subparsers(dest="comando", required=True)
    exp = comandos.add_parser("exportar", help="JSON com todos os dados do aluno")
    exp.add_argument("--aluno", required=True)
    exp.add_argument("--saida", help="arquivo de saída (padrão: titular-<código>-<data>.json); nunca sobrescreve")
    eli = comandos.add_parser("eliminar", help="anonimiza ou apaga os dados do aluno (faz cópia do banco antes)")
    eli.add_argument("--aluno", required=True)
    eli.add_argument("--confirmar", help="o mesmo código, para rodar sem pergunta (scripts)")
    args = parser.parse_args()
    criar_tabelas()
    try:
        if args.comando == "exportar":
            saida = Path(args.saida or f"titular-{args.aluno}-{datetime.now():%Y%m%d}.json")
            if saida.exists():
                raise ErroTitular(f"{saida} já existe; escolha outro --saida.")
            gravar_exportacao(exportar(args.aluno), saida)
            print(f"Dados exportados em {saida} (permissão só do dono). Entregue ao titular por canal seguro "
                  "e apague o arquivo depois.")
        else:
            confirmacao = args.confirmar
            if confirmacao is None:
                print(f"ATENÇÃO: os dados do aluno {args.aluno} serão eliminados ou anonimizados e o usuário "
                      "ligado será desativado. Uma cópia do banco é feita antes.")
                confirmacao = input("Digite o código do aluno de novo para confirmar: ").strip()
            resumo = eliminar(args.aluno, confirmacao)
            print(f"Eliminação concluída. Protocolo: {resumo['protocolo']}")
            print(f"Cópia do banco antes da eliminação: {resumo['copia']} "
                  "(sai pela retenção depois de RETENCAO_COPIAS_DIAS)")
            print(json.dumps({k: v for k, v in resumo.items() if k not in ("protocolo", "copia")}, ensure_ascii=False))
    except (ErroTitular, EOFError) as erro:
        sys.exit(f"Erro: {erro or 'confirmação não recebida'}; nada foi alterado.")
