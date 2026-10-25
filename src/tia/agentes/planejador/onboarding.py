"""
Onboarding conversacional do Agente 1 (Planejador): conversa curta que
coleta o que o aluno precisa DECLARAR para o plano (contrato 1.3.2):
trilha (dev ou defesa_cibernetica), horas por semana, dias (opcional) e
objetivo (opcional), com confirmação no fim.

Divisão de responsabilidades:
    - LLM local (R07) ou, sem ele, regras: ENTENDER a resposta livre e
      extrair campos ("umas 2h por dia, menos fim de semana" -> 10 h/semana);
    - código: VALIDAR os campos e DECIDIR a próxima pergunta. O LLM nunca
      decide sozinho que o onboarding terminou: quem decide é a confirmação.

Conhecimento NÃO é perguntado: vem do diagnóstico (diagnostico.py).

LGPD (R08): o texto do aluno vai só ao LLM local; o histórico da conversa é
apagado quando o onboarding termina (fica só o resultado), e nada vai para
log. O objetivo é texto livre do aluno: a tela pede para não pôr dados pessoais,
só o próprio aluno o recebe de volta (o docente não) e a retenção o apaga após
RETENCAO_DIALOGO_DIAS; o cadastro abandonado (com a conversa) também sai nesse prazo
(seguranca.retencao).

Limite (ONBOARDING_MAX_MENSAGENS): cada conversa aceita no máximo esse número de
mensagens do aluno (depois, ErroOnboarding: é preciso recomeçar), e o LLM é chamado
no máximo esse número de vezes por aluno, somando as conversas recomeçadas; depois
disso a extração segue só por regras. Assim um aluno não gera chamadas ilimitadas.

Não é executável sozinho; rotas em tia.api.rotas_primeiro_acesso.

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL (opcional: sem ele, extração por regras)
    - tabelas criadas/migradas: python -m tia.core.database
"""

import json
import logging
import re
import unicodedata
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from tia.core import auditoria
from tia.core import config
from tia.core.config import ONBOARDING_TIMEOUT_LLM, ONBOARDING_USA_LLM
from tia.core.database import obter_conexao
from tia.core.llm_client import chamar_llm

log = logging.getLogger(__name__)

DIAS = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
NOME_TRILHA = {"dev": "Desenvolvimento de Software", "defesa_cibernetica": "Defesa Cibernética"}
# Textos ao aluno (validados pela Pessoa 4)
SAUDACAO = ("Olá! Sou o tutor do Sistema TIA. Antes de montar seu plano de estudo, preciso de algumas "
            "informações rápidas.\n\nQual trilha você quer seguir: Desenvolvimento de Software (Dev) ou "
            "Defesa Cibernética? Se estiver em dúvida, é só dizer.")
EXPLICACAO_TRILHAS = (
    "São duas trilhas, e as duas começam pela mesma base de Python:\n"
    "• Desenvolvimento de Software (Dev): algoritmos, arquitetura, testes, bancos de dados, DevOps e APIs, "
    "para quem quer construir sistemas.\n"
    "• Defesa Cibernética: redes, criptografia, segurança de aplicações, ataque e defesa em laboratório e "
    "nuvem, para quem quer proteger e analisar sistemas.\n"
    "Qual delas você prefere?")
PERGUNTA_HORAS = ("Quantas horas por semana você consegue dedicar ao estudo? Pode responder do seu jeito, por "
                  "exemplo: \"2h por dia, menos no fim de semana\".")
PERGUNTA_OBJETIVO = ("Você tem algum objetivo com essa trilha (por exemplo: estágio, projeto final, "
                     "certificação)? Se não tiver, responda \"pular\". Não escreva dados pessoais.")
CONCLUSAO = "Perfeito! Agora vem um diagnóstico rápido (cerca de 15 minutos) para montar seu plano."

Pergunta = Literal["trilha", "horas", "objetivo", "confirmacao", "fim"]


class SessaoOnboarding(BaseModel):
    aluno_id: str
    dados: dict = Field(default_factory=dict)
    ultima_pergunta: Pergunta = "trilha"
    perguntados: list[str] = Field(default_factory=list)
    historico: list[dict] = Field(default_factory=list)
    concluido: bool = False
    mensagens: int = 0      # mensagens do aluno nesta conversa (limite ONBOARDING_MAX_MENSAGENS)
    chamadas_llm: int = 0   # chamadas ao LLM do aluno, somando as conversas recomeçadas (mesmo limite)


class RespostaOnboarding(BaseModel):
    resposta: str
    dados: dict
    concluido: bool
    proxima_pergunta: Pergunta
    origem: Literal["LLM", "regras"]


class ErroOnboarding(ValueError):
    """Erro de uso do onboarding (mensagem pensada para o usuário)."""


# --- extração por regras (sem LLM, ou se o LLM falhar) ---

def _norm(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def _num(texto: str) -> float:
    return float(texto.replace(",", "."))


def extrair_por_regras(texto: str, ultima_pergunta: str) -> dict:
    t = _norm(texto)
    saida: dict = {}
    if ultima_pergunta == "trilha" and re.search(r"\b(nao sei|duvida|diferenca|tanto faz)\b", t):
        saida["duvida_trilha"] = True
    # a trilha só é lida quando foi perguntada (ou numa correção do resumo): "estágio em
    # segurança" na pergunta de objetivo não troca a trilha
    if ultima_pergunta in ("trilha", "confirmacao"):
        if re.search(r"\b(ciber|cyber|seguranca|defesa|hack|pentest|forense|blue team|red team)", t):
            saida["trilha"] = "defesa_cibernetica"
        elif re.search(r"\b(dev\b|desenvolv|software|programa|backend|frontend|full ?stack)", t):
            saida["trilha"] = "dev"
    dias: list[str] = []
    if re.search(r"(menos|exceto|sem|fora)( n?o)? (fim de semana|fds)", t) or \
            re.search(r"\b(dias uteis|segunda a sexta|seg a sex)\b", t):
        dias = DIAS[:5]
    elif re.search(r"\b(todo dia|todos os dias|diariamente)\b", t):
        dias = DIAS[:]
    else:
        # palavras inteiras; "ter" sozinho é verbo, então só "terca" conta
        mapa = {"seg": r"\bseg(unda)?\b", "ter": r"\bterca\b", "qua": r"\bqua(rta)?\b", "qui": r"\bqui(nta)?\b",
                "sex": r"\bsex(ta)?\b", "sab": r"\bsab(ado)?\b", "dom": r"\bdom(ingo)?\b"}
        dias = [d for d, rx in mapa.items() if re.search(rx, t)]
        if re.search(r"\b(fim de semana|fds)\b", t) and not dias:
            dias = ["sab", "dom"]
    if dias:
        saida["dias_disponiveis"] = dias
    por_semana = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:h|hr|hrs|hora|horas)?\s*(?:por|/|na|a)\s*semana", t)
    por_dia = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:h|hr|hrs|hora|horas)\s*(?:por|/|ao|a|todo|cada)\s*dia", t)
    so_numero = re.fullmatch(r"\s*(?:umas?|cerca de|uns)?\s*(\d+(?:[.,]\d+)?)\s*(?:h|hr|hrs|hora|horas)?\s*", t)
    if por_semana:
        saida["horas_semana"] = _num(por_semana.group(1))
    elif por_dia:
        saida["horas_semana"] = _num(por_dia.group(1)) * (len(dias) if dias else 5)
        saida.setdefault("dias_disponiveis", dias or DIAS[:5])
    elif so_numero and ultima_pergunta == "horas":
        saida["horas_semana"] = _num(so_numero.group(1))
    if ultima_pergunta == "confirmacao":
        if re.search(r"\b(nao|errado|corrig|mudar|alterar|trocar)\b", t):
            saida["confirmou"] = False
        elif re.search(r"\b(sim|isso|confirmo|ok|certo|pode|correto|exato|beleza|show)\b", t):
            saida["confirmou"] = True
    if ultima_pergunta == "objetivo":
        saida["objetivo"] = "" if re.search(r"\b(pular|nenhum|nao sei|sem objetivo|tanto faz)\b", t) \
            else texto.strip()[:200]
    return saida


# --- extração pelo LLM local ---

PROMPT_EXTRACAO = """Você extrai dados da resposta de um aluno no cadastro de uma plataforma de estudos.
Responda SOMENTE com um objeto JSON com estas chaves (use null quando a resposta não informar):
"trilha": "dev" (desenvolvimento de software) ou "defesa_cibernetica" (segurança, redes, defesa);
"horas_semana": número de horas POR SEMANA (converta: "2h por dia, de segunda a sexta" = 10);
"dias_disponiveis": lista com valores entre "seg","ter","qua","qui","sex","sab","dom";
"objetivo": objetivo do aluno em poucas palavras (só se a pergunta foi sobre objetivo);
"confirmou": true ou false, só se a pergunta foi a confirmação do resumo;
"duvida_trilha": true se o aluno disse que não sabe qual trilha escolher.
Não invente valores.
Pergunta feita ao aluno: {pergunta}
Resposta do aluno: {texto}"""


def _json_da_resposta(texto: str) -> dict:
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL)
    achado = re.search(r"\{.*\}", texto, flags=re.DOTALL)
    if not achado:
        raise ValueError("resposta sem JSON")
    dados = json.loads(achado.group(0))
    if not isinstance(dados, dict):
        raise ValueError("JSON não é um objeto")
    return {k: v for k, v in dados.items() if v is not None}


def extrair_com_llm(texto: str, ultima_pergunta: str) -> dict:
    resposta = chamar_llm(PROMPT_EXTRACAO.format(pergunta=ultima_pergunta, texto=texto), think=False,
                          timeout=ONBOARDING_TIMEOUT_LLM, temperatura=0.0)
    return _json_da_resposta(resposta)


# --- validação e diálogo ---

def _validar(campos: dict) -> dict:
    """Mantém só os campos válidos; o resto é ignorado (o aluno é perguntado de novo)."""
    ok: dict = {}
    if campos.get("trilha") in NOME_TRILHA:
        ok["trilha"] = campos["trilha"]
    horas = campos.get("horas_semana")
    if isinstance(horas, (int, float)) and not isinstance(horas, bool) and 0 < horas <= 60:
        ok["horas_semana"] = round(float(horas), 1)
    dias = campos.get("dias_disponiveis")
    if isinstance(dias, list) and dias and all(d in DIAS for d in dias):
        ok["dias_disponiveis"] = [d for d in DIAS if d in dias]
    if isinstance(campos.get("objetivo"), str):
        ok["objetivo"] = campos["objetivo"].strip()[:200]
    for chave in ("confirmou", "duvida_trilha"):
        if isinstance(campos.get(chave), bool):
            ok[chave] = campos[chave]
    return ok


def _resumo(dados: dict, prazo_dias: int | None) -> str:
    linhas = [f"• Trilha: {NOME_TRILHA[dados['trilha']]}",
              f"• Tempo de estudo: {dados['horas_semana']:g} h por semana"]
    if dados.get("dias_disponiveis"):
        linhas.append(f"• Dias: {', '.join(dados['dias_disponiveis'])}")
    if dados.get("objetivo"):
        linhas.append(f"• Objetivo: {dados['objetivo']}")
    if prazo_dias:
        linhas.append(f"• Prazo: {prazo_dias} dias")
    return "Confere se está tudo certo:\n" + "\n".join(linhas) + "\n\nPosso seguir? (sim/não)"


def nova_sessao(aluno_id: str, anterior: SessaoOnboarding | None = None) -> tuple[SessaoOnboarding, str]:
    """Conversa nova; as chamadas ao LLM da conversa anterior continuam contando."""
    sessao = SessaoOnboarding(aluno_id=aluno_id, perguntados=["trilha"],
                              historico=[{"papel": "tutor", "texto": SAUDACAO}],
                              chamadas_llm=anterior.chamadas_llm if anterior else 0)
    return sessao, SAUDACAO


def processar(sessao: SessaoOnboarding, texto: str, prazo_dias: int | None = None,
              usar_llm: bool | None = None) -> RespostaOnboarding:
    """Uma resposta do aluno -> próxima pergunta (altera a sessão recebida).
    usar_llm None: ONBOARDING_USA_LLM."""
    if sessao.concluido:
        raise ErroOnboarding("O cadastro já foi concluído.")
    limite = config.ONBOARDING_MAX_MENSAGENS
    if sessao.mensagens >= limite:
        raise ErroOnboarding(f"Limite de {limite} mensagens desta conversa atingido. Recomece o cadastro.")
    sessao.mensagens += 1
    sessao.historico.append({"papel": "aluno", "texto": texto})
    campos, origem = {}, "regras"
    if (ONBOARDING_USA_LLM if usar_llm is None else usar_llm) and sessao.chamadas_llm < limite:
        sessao.chamadas_llm += 1
        try:
            campos, origem = extrair_com_llm(texto, sessao.ultima_pergunta), "LLM"
        except Exception as erro:  # qualquer falha do LLM: segue por regras
            log.warning("Onboarding sem LLM (%s); usando regras.", type(erro).__name__)
            campos = {}
    if not _validar(campos):
        campos, origem = extrair_por_regras(texto, sessao.ultima_pergunta), "regras"
    campos = _validar(campos)
    confirmou = campos.pop("confirmou", None)
    duvida = campos.pop("duvida_trilha", False)
    novos = {k: v for k, v in campos.items() if sessao.dados.get(k) != v}
    sessao.dados.update(campos)
    dados = sessao.dados

    if sessao.ultima_pergunta == "confirmacao" and confirmou is True and not novos:
        sessao.concluido, proxima, resposta = True, "fim", CONCLUSAO
    elif "trilha" not in dados:
        proxima = "trilha"
        resposta = EXPLICACAO_TRILHAS if duvida else \
            "Não entendi qual trilha você prefere. É Dev (desenvolvimento) ou Defesa Cibernética?"
    elif "horas_semana" not in dados:
        proxima, resposta = "horas", PERGUNTA_HORAS
    elif "objetivo" not in dados and "objetivo" not in sessao.perguntados:
        proxima, resposta = "objetivo", PERGUNTA_OBJETIVO
    elif sessao.ultima_pergunta == "confirmacao" and confirmou is False and not novos:
        proxima, resposta = "confirmacao", "Sem problema. O que você quer corrigir? Pode me dizer o valor certo."
    else:
        proxima, resposta = "confirmacao", _resumo(dados, prazo_dias)

    sessao.ultima_pergunta = proxima
    if proxima not in sessao.perguntados:
        sessao.perguntados.append(proxima)
    sessao.historico.append({"papel": "tutor", "texto": resposta})
    if sessao.concluido:
        sessao.historico = []  # minimização (R08): só o resultado fica guardado
    return RespostaOnboarding(resposta=resposta, dados=dict(dados), concluido=sessao.concluido,
                              proxima_pergunta=proxima, origem=origem)


# --- persistência ---

def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def salvar(sessao: SessaoOnboarding, auditar: str | None = None):
    agora = _agora()
    conexao = obter_conexao()
    try:
        with conexao:
            conexao.execute(
                """INSERT INTO planejador_onboarding (aluno_id, estado, concluido, criado_em, atualizado_em)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(aluno_id) DO UPDATE SET estado = excluded.estado, concluido = excluded.concluido,
                       atualizado_em = excluded.atualizado_em""",
                (sessao.aluno_id, sessao.model_dump_json(), sessao.concluido, agora, agora))
            if auditar:  # sem o texto do aluno: só o que foi decidido
                auditoria.registrar(conexao, sessao.aluno_id, "onboarding", sessao.ultima_pergunta, auditar, [],
                                    motivo=f"campos: {', '.join(sorted(sessao.dados)) or '-'}"
                                           + ("; concluído" if sessao.concluido else ""))
    finally:
        conexao.close()


def ler(aluno_id: str) -> SessaoOnboarding | None:
    conexao = obter_conexao()
    try:
        linha = conexao.execute("SELECT estado FROM planejador_onboarding WHERE aluno_id = ?",
                                (aluno_id,)).fetchone()
    finally:
        conexao.close()
    return SessaoOnboarding.model_validate_json(linha["estado"]) if linha else None
