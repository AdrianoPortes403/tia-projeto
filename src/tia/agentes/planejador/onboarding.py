"""
Onboarding conversacional do Agente 1 (Planejador): conversa curta que
coleta o que o aluno precisa DECLARAR para o plano (contrato 1.3.2):
trilha (dev ou defesa_cibernetica), horas por semana, dias (opcional) e
objetivo (opcional), com confirmação no fim.

Divisão de responsabilidades:
    - código (regras): ENTENDER a resposta e DECIDIR. Cada pergunta só grava
      os seus campos; dias, objetivo e a confirmação são só do código; a
      matrícula exige "sim" explícito no resumo, e "não" volta às perguntas;
    - LLM local (R07), só nas perguntas de trilha e de horas: SUGERE o valor
      quando as regras não entendem ("duas horinhas nos dias de semana" ->
      10 h/semana). A sugestão só é aceita se estiver ancorada no texto do
      aluno (a trilha citada por ele; horas a partir dos números que ele
      escreveu). Campo de outra pergunta, valor inventado ou copiado do
      prompt é descartado. Correção de 01/11/2026:
      docs/relatorios/correcao_onboarding.md.

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


# --- regras do código: o que vale como resposta do aluno ---
#
# Correção de 01/11/2026 (docs/relatorios/correcao_onboarding.md): com o qwen3:1.7b, o LLM devolvia
# campos que o aluno não disse (trilha, horas, dias e objetivo de uma vez, ou o exemplo do prompt) e o
# código gravava. Agora:
#   1. cada pergunta só grava os SEUS campos (CAMPOS_DA_PERGUNTA); o resto que vier é descartado;
#   2. todo valor aceito é ANCORADO no texto do aluno deste turno: trilha só se a mensagem cita palavras
#      dela; horas só se o número sai dos números escritos pelo aluno; mensagem vaga não grava nada;
#   3. dias, objetivo e a confirmação são decididos só pelo código (o LLM nunca os escreve);
#   4. a confirmação exige "sim" explícito; "não" sem correção volta ao começo das perguntas.

# campos que cada pergunta pode gravar (dias vêm junto da resposta de horas, decididos pelo código;
# na confirmação, só correções ancoradas no texto, decididas pelo código)
CAMPOS_DA_PERGUNTA = {
    "trilha": ("trilha",),
    "horas": ("horas_semana", "dias_disponiveis"),
    "objetivo": ("objetivo",),
    "confirmacao": ("trilha", "horas_semana", "dias_disponiveis"),
}
# perguntas em que o LLM é consultado (nas outras, só o código)
PERGUNTAS_COM_LLM = ("trilha", "horas")

# PROVISÓRIO (textos novos de 01/11/2026, a validar com a Pessoa 4)
TRILHA_DE_NOVO = ("Não entendi qual trilha você prefere. Responda \"Dev\" (Desenvolvimento de Software) ou "
                  "\"Defesa Cibernética\". Se quiser, pergunte a diferença.")
HORAS_DE_NOVO = ("Não entendi quantas horas. Responda com um número, por exemplo: \"5 horas por semana\" ou "
                 "\"1 hora por dia\".")
CONFIRMACAO_DE_NOVO = "Preciso de uma resposta clara: os dados acima estão certos? Responda \"sim\" ou \"não\"."
REFAZER = "Sem problema, vamos refazer o cadastro.\n\n"

PALAVRAS_TRILHA = {
    "defesa_cibernetica": r"\b(ciber\w*|cyber\w*|seguranca|defesa|hack\w*|pentest\w*|forense|blue team|red team)\b",
    "dev": r"\b(dev|desenvolv\w*|software|programa\w*|programar|backend|back end|frontend|front end|full ?stack)\b",
}
DUVIDA_TRILHA = r"\b(nao sei|duvida|diferenca|diferente|tanto faz|qualquer uma|nao tenho certeza|qual (e )?(a )?melhor)\b"
NUMEROS_ESCRITOS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
                    "sete": 7, "oito": 8, "nove": 9, "dez": 10, "doze": 12, "quinze": 15, "vinte": 20}
SIM = r"\b(sim|s|confirmo|confirmado|correto|certo|isso|exato|ok|pode seguir)\b"
NAO = r"\b(nao|n|errado|incorreto|corrig\w*|mudar|alterar|trocar)\b"


def _norm(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def _num(texto: str) -> float:
    return float(texto.replace(",", "."))


def _com_algarismos(t: str) -> str:
    """'duas horas e meia' -> '2.5 horas' (texto já normalizado)."""
    t = re.sub(r"\b(" + "|".join(NUMEROS_ESCRITOS) + r")\b", lambda m: str(NUMEROS_ESCRITOS[m.group(1)]), t)
    t = re.sub(r"(\d+)\s*(h|hr|hrs|hora|horas)?\s+e\s+meia\b", r"\g<1>.5 \2", t)
    return re.sub(r"\bmeia hora\b", "0.5 hora", t)


def trilhas_citadas(texto: str) -> set[str]:
    """Trilhas cujas palavras aparecem no texto sem negação logo antes ("não quero dev" não conta)."""
    t = _norm(texto)
    citadas = set()
    for trilha, padrao in PALAVRAS_TRILHA.items():
        for achado in re.finditer(padrao, t):
            antes = t[max(0, achado.start() - 30):achado.start()]
            if not re.search(r"\bnao\b(\s+\w+){0,2}\s*$", antes):
                citadas.add(trilha)
    return citadas


def _dias(t: str) -> list[str]:
    if re.search(r"(menos|exceto|sem|fora)( n?o)? (fim de semana|fds)", t) or \
            re.search(r"\b(dias uteis|dias de semana|segunda a sexta|seg a sex)\b", t):
        return DIAS[:5]
    if re.search(r"\b(todo dia|todos os dias|diariamente)\b", t):
        return DIAS[:]
    # palavras inteiras; "ter" sozinho é verbo, então só "terca" conta
    mapa = {"seg": r"\bseg(unda)?\b", "ter": r"\bterca\b", "qua": r"\bqua(rta)?\b", "qui": r"\bqui(nta)?\b",
            "sex": r"\bsex(ta)?\b", "sab": r"\bsab(ado)?\b", "dom": r"\bdom(ingo)?\b"}
    dias = [d for d, rx in mapa.items() if re.search(rx, t)]
    if re.search(r"\b(fim de semana|fds)\b", t) and not dias:
        dias = ["sab", "dom"]
    return dias


def _horas_e_dias(texto: str, ultima_pergunta: str) -> dict:
    """Horas por semana e dias, só pelo texto (regras)."""
    t = _com_algarismos(_norm(texto))
    saida: dict = {}
    dias = _dias(t)
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
    return saida


def horas_ancoradas(valor, texto: str) -> bool:
    """O número de horas sai dos números que o aluno escreveu (o próprio número, ou por dia vezes
    os dias citados, 5 ou 7)? Barra o LLM que inventa ou copia o exemplo do prompt."""
    if not isinstance(valor, (int, float)) or isinstance(valor, bool) or not 0 < valor <= 60:
        return False
    t = _com_algarismos(_norm(texto))
    numeros = [_num(n) for n in re.findall(r"\d+(?:[.,]\d+)?", t)]
    multiplicadores = {1, 5, 7, len(_dias(t)) or 5}
    return any(abs(valor - n * m) < 0.01 for n in numeros for m in multiplicadores)


def _confirmacao(texto: str) -> bool | None:
    """True só com "sim" explícito; False com "não"; None se não dá para saber (inclusive com os dois:
    "sim, não precisa mudar" pede a resposta de novo, em vez de adivinhar)."""
    t = _norm(texto)
    sim, nao = bool(re.search(SIM, t)), bool(re.search(NAO, t))
    if sim == nao:
        return None
    return sim


def extrair_por_regras(texto: str, ultima_pergunta: str) -> dict:
    """O que o CÓDIGO entende da resposta, só com os campos da pergunta da vez."""
    t = _norm(texto)
    saida: dict = {}
    if ultima_pergunta in ("trilha", "confirmacao"):
        duvida = bool(re.search(DUVIDA_TRILHA, t))
        citadas = trilhas_citadas(texto)
        if ultima_pergunta == "trilha" and duvida:
            saida["duvida_trilha"] = True
        elif len(citadas) == 1:  # citou as duas, ou nenhuma: não decide
            saida["trilha"] = citadas.pop()
    if ultima_pergunta in ("horas", "confirmacao"):
        saida.update(_horas_e_dias(texto, ultima_pergunta))
    if ultima_pergunta == "objetivo":
        saida["objetivo"] = "" if re.search(r"\b(pular|nenhum|nao sei|sem objetivo|tanto faz|nao tenho)\b", t) \
            else texto.strip()[:200]
    if ultima_pergunta == "confirmacao":
        confirmou = _confirmacao(texto)
        if confirmou is not None:
            saida["confirmou"] = confirmou
    return saida


# --- extração pelo LLM local (só trilha e horas; o código confere) ---

PROMPT_TRILHA = """Um aluno respondeu à pergunta: "Qual trilha você quer seguir: Desenvolvimento de Software \
(Dev) ou Defesa Cibernética?".
Responda SOMENTE com um objeto JSON com as chaves "trilha" e "duvida_trilha".
"trilha": "dev" ou "defesa_cibernetica" se o aluno ESCOLHEU uma delas; null se não escolheu.
"duvida_trilha": true se o aluno disse que não sabe ou perguntou a diferença; senão false.
Resposta do aluno: {texto}"""

PROMPT_HORAS = """Um aluno respondeu à pergunta: "Quantas horas por semana você consegue dedicar ao estudo?".
Responda SOMENTE com um objeto JSON com a chave "horas_semana": o total de horas POR SEMANA que o aluno \
informou (se ele falou em horas por dia, multiplique pelos dias que ele citou), ou null se ele não informou \
um número.
Resposta do aluno: {texto}"""

PROMPTS = {"trilha": PROMPT_TRILHA, "horas": PROMPT_HORAS}


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
    """Pedido ao LLM só sobre a pergunta da vez. O resultado é uma SUGESTÃO: ver aceitar_do_llm."""
    resposta = chamar_llm(PROMPTS[ultima_pergunta].format(texto=texto), think=False,
                          timeout=ONBOARDING_TIMEOUT_LLM, temperatura=0.0)
    return _json_da_resposta(resposta)


def aceitar_do_llm(sugestao: dict, texto: str, ultima_pergunta: str) -> dict:
    """Do que o LLM sugeriu, só o campo da pergunta da vez e só se ancorado no texto do aluno."""
    aceito: dict = {}
    if ultima_pergunta == "trilha":
        trilha = sugestao.get("trilha")
        # aceita a escolha do LLM só entre as trilhas que o aluno citou (quando citou as duas, o LLM desempata)
        if trilha in NOME_TRILHA and trilha in trilhas_citadas(texto) and \
                not re.search(DUVIDA_TRILHA, _norm(texto)):
            aceito["trilha"] = trilha
    elif ultima_pergunta == "horas":
        if horas_ancoradas(sugestao.get("horas_semana"), texto):
            aceito["horas_semana"] = round(float(sugestao["horas_semana"]), 1)
    return aceito


# --- validação e diálogo ---

def _validar(campos: dict) -> dict:
    """Mantém só os campos com valor válido."""
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


def dados_completos(dados: dict) -> bool:
    """Os campos obrigatórios para a matrícula estão presentes e válidos."""
    validos = _validar(dados)
    return "trilha" in validos and "horas_semana" in validos


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


def _entender(sessao: SessaoOnboarding, texto: str, usar_llm: bool) -> tuple[dict, str]:
    """Campos desta resposta (só os da pergunta da vez, ancorados no texto) e a origem."""
    pergunta = sessao.ultima_pergunta
    regras = extrair_por_regras(texto, pergunta)
    sugestao: dict = {}
    if usar_llm and pergunta in PERGUNTAS_COM_LLM and sessao.chamadas_llm < config.ONBOARDING_MAX_MENSAGENS:
        sessao.chamadas_llm += 1
        try:
            sugestao = extrair_com_llm(texto, pergunta)
        except Exception as erro:  # qualquer falha do LLM: segue por regras
            log.warning("Onboarding sem LLM (%s); usando regras.", type(erro).__name__)
    do_llm = aceitar_do_llm(sugestao, texto, pergunta)
    # o código decide: dias, objetivo e confirmação vêm só das regras; trilha e horas, das regras
    # quando elas entendem, senão da sugestão do LLM que passou na âncora
    campos = dict(regras)
    for chave, valor in do_llm.items():
        campos.setdefault(chave, valor)
    if pergunta == "trilha" and sugestao.get("duvida_trilha") is True and "trilha" not in campos:
        campos["duvida_trilha"] = True  # dúvida não grava nada: só mostra a explicação
    permitidos = CAMPOS_DA_PERGUNTA.get(pergunta, ()) + ("confirmou", "duvida_trilha")
    campos = {k: v for k, v in _validar(campos).items() if k in permitidos}
    usou_llm = any(campos.get(k) == v for k, v in do_llm.items())
    return campos, "LLM" if usou_llm else "regras"


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
    campos, origem = _entender(sessao, texto, ONBOARDING_USA_LLM if usar_llm is None else usar_llm)
    confirmou = campos.pop("confirmou", None)
    duvida = campos.pop("duvida_trilha", False)
    pergunta = sessao.ultima_pergunta
    novos = {k: v for k, v in campos.items() if sessao.dados.get(k) != v}
    prefixo = ""

    if pergunta == "confirmacao" and confirmou is False and not novos:
        # "não" sem dizer o que corrigir: volta ao começo das perguntas, sem os valores anteriores
        sessao.dados, sessao.perguntados, prefixo = {}, ["trilha"], REFAZER
    else:
        sessao.dados.update(campos)
    dados = sessao.dados

    if pergunta == "confirmacao" and confirmou is True and not novos and dados_completos(dados):
        sessao.concluido, proxima, resposta = True, "fim", CONCLUSAO
    elif "trilha" not in dados:
        proxima = "trilha"
        resposta = prefixo + (SAUDACAO.split("\n\n", 1)[1] if prefixo else
                              EXPLICACAO_TRILHAS if duvida else TRILHA_DE_NOVO)
    elif "horas_semana" not in dados:
        proxima, resposta = "horas", HORAS_DE_NOVO if pergunta == "horas" else PERGUNTA_HORAS
    elif "objetivo" not in dados and "objetivo" not in sessao.perguntados:
        proxima, resposta = "objetivo", PERGUNTA_OBJETIVO
    elif pergunta == "confirmacao" and confirmou is None and not novos:
        proxima, resposta = "confirmacao", CONFIRMACAO_DE_NOVO + "\n\n" + _resumo(dados, prazo_dias)
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
