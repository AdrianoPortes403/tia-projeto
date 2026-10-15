"""
Diagnóstico inicial do aluno (base pedagógica 1.2.5, seção 2), insumo do
Agente 1 (Planejador): enquadra o perfil e tira da trilha o que já é dominado.

Regras (PURAS e determinísticas: sem LLM nem aleatoriedade):
    - cobre os tópicos da base comum (etapa 0) e da etapa 1 da trilha escolhida
      que têm item de diagnóstico ("uso": "diagnostico") nos três níveis;
    - em cada tópico, aplica os níveis 1 -> 2 -> 3 e para no primeiro erro;
    - nota do tópico (convenção do Planejador): errou o nível 1 = 0; errou o
      2 = 1/3; errou o 3 = 2/3; acertou os três = 1 (dominado).

A sessão fica em planejador_diagnosticos (uma por aluno, refeita se o aluno
recomeçar antes da matrícula). Os itens respondidos ficam guardados para o
Tutor não repeti-los. Cada resposta vai para a auditoria (R11), sem texto livre.

Não é executável sozinho; rotas em tia.api.rotas_primeiro_acesso.

Pré-requisitos:
    - conteudo/ementa/ementa.json e conteudo/banco_itens/itens.json
    - tabelas criadas/migradas: python -m tia.core.database
"""

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime

from tia.agentes.planejador.planejar import carregar_ementa, selecionar
from tia.core import auditoria
from tia.core.config import BANCO_ITENS_PATH
from tia.core.database import obter_conexao


class ErroDiagnostico(ValueError):
    """Erro de uso do diagnóstico (mensagem pensada para o usuário)."""


class DiagnosticoInexistente(ErroDiagnostico):
    pass


class RespostaForaDeOrdem(ErroDiagnostico):
    pass


@dataclass(frozen=True)
class EstadoDiagnostico:
    trilha: str | None
    topicos: tuple[str, ...]
    indice: int = 0                      # tópico atual em topicos
    nivel: int = 1
    item_atual_id: str | None = None     # None quando concluído
    notas: dict = field(default_factory=dict)
    respondidos: tuple[str, ...] = ()
    concluido: bool = False


def carregar_itens(caminho: str = BANCO_ITENS_PATH) -> list[dict]:
    with open(caminho, encoding="utf-8") as arquivo:
        return json.load(arquivo)["itens"]


def item_de_diagnostico(itens: list[dict], topico: str, nivel: int) -> dict | None:
    """Primeiro item de diagnóstico do tópico no nível (ordem do banco)."""
    return next((i for i in itens if i["competencia_id"] == topico and i["nivel"] == nivel
                 and i.get("uso") == "diagnostico"), None)


def topicos_do_diagnostico(trilha: str | None, ementa: list[dict], itens: list[dict]) -> list[str]:
    """Tópicos da base comum e da etapa 1 da trilha com item de diagnóstico nos 3 níveis."""
    return [c["id"] for c in selecionar(ementa, trilha) if c.get("etapa", 0) in (0, 1)
            and all(item_de_diagnostico(itens, c["id"], n) for n in (1, 2, 3))]


def iniciar(trilha: str | None, ementa: list[dict], itens: list[dict]) -> EstadoDiagnostico:
    topicos = tuple(topicos_do_diagnostico(trilha, ementa, itens))
    if not topicos:
        return EstadoDiagnostico(trilha=trilha, topicos=(), concluido=True)
    return EstadoDiagnostico(trilha=trilha, topicos=topicos,
                             item_atual_id=item_de_diagnostico(itens, topicos[0], 1)["id"])


def avancar(estado: EstadoDiagnostico, itens: list[dict], acertou: bool) -> EstadoDiagnostico:
    """Registra a resposta ao item atual e devolve o novo estado."""
    if estado.concluido or estado.item_atual_id is None:
        raise RespostaForaDeOrdem("O diagnóstico já foi concluído.")
    respondidos = estado.respondidos + (estado.item_atual_id,)
    topico = estado.topicos[estado.indice]
    if acertou and estado.nivel < 3:
        nivel = estado.nivel + 1
        return replace(estado, nivel=nivel, respondidos=respondidos,
                       item_atual_id=item_de_diagnostico(itens, topico, nivel)["id"])
    nota = 1.0 if acertou else round((estado.nivel - 1) / 3, 4)
    notas = {**estado.notas, topico: nota}
    indice = estado.indice + 1
    if indice >= len(estado.topicos):
        return replace(estado, indice=indice, nivel=1, item_atual_id=None, notas=notas, respondidos=respondidos,
                       concluido=True)
    return replace(estado, indice=indice, nivel=1, notas=notas, respondidos=respondidos,
                   item_atual_id=item_de_diagnostico(itens, estado.topicos[indice], 1)["id"])


# --- persistência ---

def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _para_json(estado: EstadoDiagnostico) -> str:
    dados = asdict(estado)
    dados["topicos"], dados["respondidos"] = list(estado.topicos), list(estado.respondidos)
    return json.dumps(dados, ensure_ascii=False)


def _de_json(texto: str) -> EstadoDiagnostico:
    dados = json.loads(texto)
    dados["topicos"], dados["respondidos"] = tuple(dados["topicos"]), tuple(dados["respondidos"])
    return EstadoDiagnostico(**dados)


def salvar(aluno_id: str, estado: EstadoDiagnostico):
    agora = _agora()
    conexao = obter_conexao()
    try:
        with conexao:
            conexao.execute(
                """INSERT INTO planejador_diagnosticos (aluno_id, trilha, estado, concluido, criado_em, atualizado_em)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(aluno_id) DO UPDATE SET trilha = excluded.trilha, estado = excluded.estado,
                       concluido = excluded.concluido, atualizado_em = excluded.atualizado_em""",
                (aluno_id, estado.trilha, _para_json(estado), estado.concluido, agora, agora))
    finally:
        conexao.close()


def ler(aluno_id: str) -> EstadoDiagnostico | None:
    conexao = obter_conexao()
    try:
        linha = conexao.execute("SELECT estado FROM planejador_diagnosticos WHERE aluno_id = ?",
                                (aluno_id,)).fetchone()
    finally:
        conexao.close()
    return _de_json(linha["estado"]) if linha else None


def itens_respondidos(aluno_id: str) -> set[str]:
    """Itens que o aluno já viu no diagnóstico (o Tutor não os repete)."""
    estado = ler(aluno_id)
    return set(estado.respondidos) if estado else set()


def comecar(aluno_id: str, trilha: str | None) -> EstadoDiagnostico:
    """Inicia (ou recomeça) o diagnóstico do aluno na trilha."""
    estado = iniciar(trilha, carregar_ementa(), carregar_itens())
    salvar(aluno_id, estado)
    return estado


def responder(aluno_id: str, item_id: str, indice_escolhido: int) -> tuple[bool, EstadoDiagnostico]:
    """Corrige a resposta ao item atual, avança e grava (com auditoria)."""
    estado = ler(aluno_id)
    if estado is None:
        raise DiagnosticoInexistente("Diagnóstico não iniciado para este aluno.")
    if estado.concluido:
        raise RespostaForaDeOrdem("O diagnóstico já foi concluído.")
    if item_id != estado.item_atual_id:
        raise RespostaForaDeOrdem("A resposta não corresponde à pergunta atual do diagnóstico.")
    itens = carregar_itens()
    item = next(i for i in itens if i["id"] == item_id)
    acertou = indice_escolhido == item["indice_correto"]
    novo = avancar(estado, itens, acertou)
    conexao = obter_conexao()
    try:
        with conexao:
            conexao.execute("UPDATE planejador_diagnosticos SET estado = ?, concluido = ?, atualizado_em = ? "
                            "WHERE aluno_id = ?", (_para_json(novo), novo.concluido, _agora(), aluno_id))
            auditoria.registrar(conexao, aluno_id, "diagnostico", item_id, "regra", [],
                                motivo=f"{'acerto' if acertou else 'erro'} no nível {item['nivel']}"
                                       + ("; diagnóstico concluído" if novo.concluido else ""))
    finally:
        conexao.close()
    return acertou, novo
