"""
Testes do Agente 2 (Tutor): máquina de estados do questionário adaptativo,
feedback com fonte (llm_client e retrieve mockados), banco de itens
(PROVISÓRIO até a revisão da Pessoa 4) e migração do historico_respostas.

Como rodar:
    ./run_tests.sh tests/test_tutor.py
"""

import json
import sqlite3

import pytest
import requests

import tia.agentes.tutor.feedback as feedback
import tia.core.database as database
from tia.agentes.planejador.planejar import carregar_ementa
from tia.agentes.tutor import adaptativo
from tia.agentes.tutor.adaptativo import EstadoSessao, SemItens, avancar, corrigir, iniciar
from tia.agentes.tutor.repositorio import carregar_itens


def item(id_: str, nivel: int, competencia: str = "c") -> dict:
    return {"id": id_, "competencia_id": competencia, "nivel": nivel, "enunciado": f"Pergunta {id_}?",
            "alternativas": ["a", "b", "c", "d"], "indice_correto": 1, "explicacao": f"Explicação de {id_}."}


# banco de teste: 2 itens por nível, mais um item de outra competência
ITENS = [item("n1a", 1), item("n1b", 1), item("n2a", 2), item("n2b", 2),
         item("n3a", 3), item("n3b", 3), item("outro", 1, competencia="x")]


def responder_em_sequencia(acertos: list[bool]) -> list[EstadoSessao]:
    """Aplica as respostas a partir do início; devolve todos os estados."""
    estados = [iniciar(ITENS, "c")]
    for acertou in acertos:
        estados.append(avancar(estados[-1], ITENS, acertou))
    return estados


# --- máquina de estados (pura) ---

def test_comeca_no_nivel_1_com_o_primeiro_item():
    estado = iniciar(ITENS, "c")
    assert (estado.nivel, estado.item_atual_id, estado.concluida) == (1, "n1a", False)


# banco maior, para as regras de sequência do 1.2.5 (5 itens por nível)
ITENS5 = [item(f"m{n}{l}", n, competencia="m") for n in (1, 2, 3) for l in "abcde"]


def sequencia5(acertos: list[bool], nivel: int = 1) -> list[EstadoSessao]:
    estados = [iniciar(ITENS5, "m", nivel)]
    for acertou in acertos:
        estados.append(avancar(estados[-1], ITENS5, acertou))
    return estados


def test_sobe_com_3_acertos_seguidos_e_desce_com_2_erros_seguidos():
    # 1.2.5: 3 acertos seguidos sobem; 2 erros seguidos descem; as sequências zeram ao mudar de nível
    estados = sequencia5([True, True, True, False, True, False, False])
    assert [e.nivel for e in estados] == [1, 1, 1, 2, 2, 2, 2, 1]
    assert [(e.acertos_seguidos, e.erros_seguidos) for e in estados[3:]] == [(0, 0), (0, 1), (1, 0), (0, 1), (0, 0)]


def test_erro_isolado_nao_desce_e_acerto_isolado_nao_sobe():
    estados = sequencia5([True, False, True, False], nivel=2)
    assert {e.nivel for e in estados} == {2}


def test_dois_erros_no_nivel_1_sinalizam_lacuna_sem_descer():
    estados = sequencia5([False, False, False])
    assert [e.nivel for e in estados] == [1, 1, 1, 1]
    assert [e.lacuna for e in estados] == [False, False, True, False]  # a flag vale só para a resposta que a fechou
    assert estados[2].erros_seguidos == 0


def test_conclui_com_3_acertos_seguidos_no_nivel_3():
    estados = sequencia5([True] * 9)
    assert [e.nivel for e in estados] == [1, 1, 1, 2, 2, 2, 3, 3, 3, 3]
    assert not estados[8].concluida  # 2 acertos no nível 3 ainda não bastam
    assert estados[-1].concluida and estados[-1].acertos_seguidos_nivel_max == 3
    assert estados[-1].item_atual_id is None


def test_erro_no_nivel_3_zera_a_sequencia():
    estados = sequencia5([True, True, False], nivel=3)
    assert estados[2].acertos_seguidos_nivel_max == 2
    assert estados[3].acertos_seguidos_nivel_max == 0 and estados[3].nivel == 3  # um erro só não desce
    assert not estados[3].concluida


def test_comeca_no_nivel_do_diagnostico_e_evita_itens_ja_vistos():
    estado = iniciar(ITENS5, "m", 3, evitar={"m3a", "m3b"})
    assert (estado.nivel, estado.item_atual_id) == (3, "m3c")
    proximo = avancar(estado, ITENS5, True, evitar={"m3a", "m3b"})
    assert proximo.item_atual_id == "m3d"
    # se só sobrarem itens vistos no diagnóstico, eles voltam (melhor do que encerrar sem pergunta)
    so_vistos = [i for i in ITENS5 if i["id"] in ("m1a", "m1b")]
    assert iniciar(so_vistos, "m", 1, evitar={"m1a", "m1b"}).item_atual_id == "m1a"


def test_nao_repete_item_ate_esgotar():
    # restaurado (15/10/2026) para as regras do 1.2.5: alternando erro e acerto, a sessão usa
    # cada item da competência uma única vez, nunca pega item de outra e esgota exatamente os 6
    estados = responder_em_sequencia([False, True] * 3)
    perguntados = [e.item_atual_id for e in estados if e.item_atual_id]
    assert len(perguntados) == len(set(perguntados)) == 6
    assert "outro" not in perguntados  # nunca pega item de outra competência
    assert estados[-1].concluida and estados[-1].item_atual_id is None
    assert sorted(estados[-1].itens_usados) == ["n1a", "n1b", "n2a", "n2b", "n3a", "n3b"]
    assert estados[-1].com_ressalvas  # acabou por falta de itens, sem domínio


def test_nunca_pega_item_de_outra_competencia_mesmo_acertando_ou_errando_tudo():
    for acertou in (True, False):
        estados = responder_em_sequencia([acertou] * 6)
        assert all(e.item_atual_id != "outro" for e in estados)
        assert estados[-1].concluida and len(estados[-1].itens_usados) == 6


def test_nivel_sem_itens_usa_o_mais_proximo():
    # restaurado: erra 2 vezes no nível 1 (esgota o nível 1; lacuna, sem descer) e a terceira
    # pergunta vem do nível 2, o único a 1 de distância
    estados = responder_em_sequencia([False, False])
    assert (estados[-1].item_atual_id, estados[-1].nivel) == ("n2a", 2)


def test_nivel_esgotado_depois_de_erro_vai_para_o_mais_facil():
    # começa no 2 com só 2 itens: acerta um e erra o outro (um erro só não desce); o nível 2
    # acaba e há empate entre o 1 e o 3: depois de um erro, vai para o mais fácil
    estados = [iniciar(ITENS, "c", 2)]
    for acertou in (True, False):
        estados.append(avancar(estados[-1], ITENS, acertou))
    assert [e.nivel for e in estados] == [2, 2, 1]
    assert estados[-1].item_atual_id == "n1a"
    assert (estados[-1].acertos_seguidos, estados[-1].erros_seguidos) == (0, 0)  # as sequências recomeçam


def test_conclusao_por_dominio_nao_tem_ressalva_e_por_fim_dos_itens_tem():
    dominio = sequencia5([True] * 9)[-1]
    assert dominio.concluida and not dominio.com_ressalvas and dominio.acertos_seguidos_nivel_max == 3
    errou_tudo = responder_em_sequencia([False] * 6)[-1]
    assert errou_tudo.concluida and errou_tudo.com_ressalvas
    acertou_tudo_sem_itens = responder_em_sequencia([True] * 6)[-1]  # 2 no nível 3 não bastam
    assert acertou_tudo_sem_itens.concluida and acertou_tudo_sem_itens.com_ressalvas


def test_nivel_esgotado_depois_de_acerto_nao_desce():
    # nível 2 com só 2 itens: acertando os dois, o próximo vem do nível 3 (não do 1, que também está a 1 de distância)
    estados = responder_em_sequencia([True, True, True, True])  # banco de 2 por nível, começando no 1
    assert [e.nivel for e in estados] == [1, 1, 2, 2, 3]
    estados = [iniciar(ITENS, "c", 2)]
    for acertou in (True, True):
        estados.append(avancar(estados[-1], ITENS, acertou))
    assert [e.nivel for e in estados] == [2, 2, 3]


def test_limiares_vem_da_configuracao(monkeypatch):
    monkeypatch.setattr(adaptativo.config, "TUTOR_ACERTOS_SUBIR", 1)
    assert [e.nivel for e in sequencia5([True, True])] == [1, 2, 3]


def test_e_deterministica_e_nao_altera_o_estado_recebido():
    estado = iniciar(ITENS, "c")
    assert avancar(estado, ITENS, True) == avancar(estado, ITENS, True)
    assert estado == iniciar(ITENS, "c")


def test_sessao_concluida_nao_avanca_e_competencia_sem_itens_falha():
    concluida = sequencia5([True] * 9)[-1]
    with pytest.raises(ValueError):
        avancar(concluida, ITENS5, True)
    with pytest.raises(SemItens):
        iniciar(ITENS, "inexistente")


def test_corrigir():
    assert corrigir(ITENS[0], 1) is True
    assert corrigir(ITENS[0], 0) is False


# --- feedback (retrieve e llm_client mockados) ---

TRECHO = {"texto": "range(4) produz 0, 1, 2 e 3.", "fonte": "mat_c.txt", "distancia": 250.0}
# aluno marcou A (índice 0) em ITENS[0], cujo gabarito é B
FALLBACK = feedback.ResultadoFeedback("Você marcou: A) a. A resposta correta é: B) b.", "Explicação de n1a.", [], "fallback")


def mockar(monkeypatch, trechos: list[dict], resposta_llm="Explicação do LLM."):
    """Substitui retrieve e LLM; devolve as listas de chamadas de cada um."""
    buscas, prompts = [], []

    def buscar_falso(consulta, k=3, fontes=None):
        buscas.append((consulta, fontes))
        return trechos

    def llm_falso(prompt, **kwargs):
        prompts.append((prompt, kwargs))
        if isinstance(resposta_llm, Exception):
            raise resposta_llm
        return resposta_llm

    monkeypatch.setattr(feedback, "buscar_contexto", buscar_falso)
    monkeypatch.setattr(feedback, "chamar_llm", llm_falso)
    return buscas, prompts


def test_feedback_com_trecho_cita_fonte_dos_metadados(monkeypatch):
    resposta_llm = ("<think></think>Primeira frase. Segunda frase.\nTerceira frase. Quarta frase. "
                    "Fonte: arquivo_inventado.txt")
    buscas, prompts = mockar(monkeypatch, [TRECHO, {**TRECHO, "texto": "outro"}], resposta_llm)
    resultado = feedback.gerar_feedback(ITENS[0], 0, ["mat_c.txt"])
    explicacao, fontes = resultado.explicacao, resultado.fontes

    assert resultado.origem == "LLM"
    assert fontes == ["mat_c.txt"]  # só dos metadados, sem repetir; nunca do texto do LLM
    assert explicacao == "Primeira frase. Segunda frase. Terceira frase."  # no máximo 3 frases
    assert buscas[0][1] == ["mat_c.txt"]  # busca restrita ao material da competência
    prompt, kwargs = prompts[0]
    assert TRECHO["texto"] in prompt
    assert kwargs["think"] is False
    assert kwargs["timeout"] == feedback.TUTOR_TIMEOUT_LLM and kwargs["max_tokens"] == feedback.TUTOR_MAX_TOKENS
    # amostragem do feedback vem da config (padrões 0.2 / 0.9 / 42 no .env.example)
    assert (kwargs["temperatura"], kwargs["top_p"], kwargs["seed"]) == (
        feedback.TUTOR_TEMPERATURA, feedback.TUTOR_TOP_P, feedback.TUTOR_SEED)


def test_feedback_sem_trecho_usa_texto_do_item_sem_fonte(monkeypatch):
    _, prompts = mockar(monkeypatch, [])
    assert feedback.gerar_feedback(ITENS[0], 0, ["mat_c.txt"]) == FALLBACK
    assert prompts == []  # sem material, nem chama o LLM


@pytest.mark.parametrize("trecho", [
    {**TRECHO, "distancia": 999.0},           # distante demais: irrelevante
    {**TRECHO, "fonte": "outra_materia.txt"},  # fora do material da competência
])
def test_feedback_descarta_trecho_irrelevante(monkeypatch, trecho):
    _, prompts = mockar(monkeypatch, [trecho])
    assert feedback.gerar_feedback(ITENS[0], 0, ["mat_c.txt"]) == FALLBACK
    assert prompts == []


def test_feedback_competencia_sem_material_nem_busca(monkeypatch):
    buscas, _ = mockar(monkeypatch, [TRECHO])
    assert feedback.gerar_feedback(ITENS[0], 0, []) == FALLBACK
    assert buscas == []


@pytest.mark.parametrize("resposta_llm", [requests.Timeout("demorou"), "<think>só pensou</think>  "])
def test_feedback_llm_falho_ou_vazio_usa_texto_do_item(monkeypatch, resposta_llm):
    mockar(monkeypatch, [TRECHO], resposta_llm)
    falha = "timeout" if isinstance(resposta_llm, Exception) else None  # vazio não é falha do LLM
    assert feedback.gerar_feedback(ITENS[0], 0, ["mat_c.txt"]) == feedback.ResultadoFeedback(
        FALLBACK.veredito, FALLBACK.explicacao, [], "fallback", falha_llm=falha)


def test_feedback_rag_fora_do_ar_usa_texto_do_item(monkeypatch):
    def quebrado(*args, **kwargs):
        raise requests.ConnectionError("sem Ollama")

    monkeypatch.setattr(feedback, "buscar_contexto", quebrado)
    resultado = feedback.gerar_feedback(ITENS[0], 0, ["mat_c.txt"])
    assert (resultado.explicacao, resultado.origem, resultado.falha_llm) == (
        FALLBACK.explicacao, "fallback", "rag: ConnectionError")


def test_prompt_livre_informa_acerto_ou_erro_sem_dado_do_aluno():
    prompt = feedback.montar_prompt_livre(ITENS[0], 2, [TRECHO])
    assert "ERROU (escolheu C)" in prompt and "Resposta correta: B) b" in prompt
    assert "ACERTOU" in feedback.montar_prompt_livre(ITENS[0], 1, [TRECHO])


def test_modo_ancorado_envia_explicacao_verificada_e_veredito_pronto(monkeypatch):
    _, prompts = mockar(monkeypatch, [TRECHO])
    resultado = feedback.gerar_feedback(ITENS[0], 2, ["mat_c.txt"], modo="ancorado")

    assert (resultado.explicacao, resultado.fontes, resultado.origem) == ("Explicação do LLM.", ["mat_c.txt"], "LLM")
    prompt = prompts[0][0]
    assert "EXPLICAÇÃO:\nExplicação de n1a." in prompt
    assert TRECHO["texto"] in prompt and ITENS[0]["enunciado"] in prompt
    # o LLM recebe o veredito pronto e é proibido de repeti-lo ou decidi-lo
    assert "RESULTADO (já mostrado ao aluno, não repita):\nVocê marcou: C) c. A resposta correta é: B) b." in prompt
    assert "não diga se ele acertou ou errou" in prompt
    assert "Não calcule nem invente valores, resultados de código ou números" in prompt
    assert "de 2 a 3 frases" in prompt
    for proibida in ('"explicação verificada"', '"trechos"', '"material"'):
        assert proibida in prompt
    assert "[Trecho" not in prompt and "(o aluno errou)" not in prompt


# --- veredito fixo e guarda de saída ---

def test_veredito_e_texto_fixo_gerado_por_codigo():
    assert feedback.montar_veredito(ITENS[0], 1) == "Você acertou."
    assert feedback.montar_veredito(ITENS[0], 3) == "Você marcou: D) d. A resposta correta é: B) b."


@pytest.mark.parametrize("indice, veredito", [
    (1, "Você acertou."),
    (0, "Você marcou: A) a. A resposta correta é: B) b."),
])
def test_veredito_fixo_vale_para_llm_guarda_e_fallback(monkeypatch, indice, veredito):
    for trechos, resposta_llm in ([[TRECHO], "Explicação do LLM."],      # LLM
                                  [[TRECHO], "O valor é 42."],           # guarda
                                  [[], "nunca chamado"]):                # fallback
        mockar(monkeypatch, trechos, resposta_llm)
        assert feedback.gerar_feedback(ITENS[0], indice, ["mat_c.txt"]).veredito == veredito


ITEM_RANGE = {"id": "rep", "competencia_id": "repeticao", "nivel": 2,
              "enunciado": "O que imprime for i in range(3): print(i)?",
              "alternativas": ["0 1 2", "1 2 3", "0 1 2 3", "3"], "indice_correto": 0,
              "explicacao": "range(3) gera 0, 1 e 2; o 3 não entra."}
TRECHO_RANGE = {"texto": "range(n) vai de 0 até n-1; range(1, 10, 2) pula de 2 em 2.",
                "fonte": "mat_r.txt", "distancia": 100.0}


def verificar(texto: str, indice: int = 1) -> str | None:
    return feedback.verificar_explicacao(texto, ITEM_RANGE, indice, [TRECHO_RANGE])


@pytest.mark.parametrize("texto", [
    "O range(3) gera 0, 1 e 2, porque o 3 não entra.",
    "Com range(1, 10, 2) o passo é 2.",          # números só dos trechos usados
    "A contagem começa em 0 e para antes do limite.",
    "A resposta correta é a A, pois range para antes do 3.",  # citar a correta não é dizer que acertou
])
def test_guarda_mantem_saida_boa(texto):
    assert verificar(texto) is None


@pytest.mark.parametrize("texto, trecho_motivo", [
    ("O laço repete 4 vezes.", "4"),
    ("A soma dá 3.5 no final.", "3.5"),
    ("O resultado seria 10, 20.", "20"),  # 10 está no trecho; 20 não
])
def test_guarda_descarta_numero_inventado(texto, trecho_motivo):
    motivo = verificar(texto)
    assert motivo and "número" in motivo and trecho_motivo in motivo


def test_guarda_aceita_decimal_com_virgula_se_o_numero_existe():
    item = {**ITEM_RANGE, "enunciado": "Qual o tipo de 3.14?"}
    assert feedback.verificar_explicacao("O valor 3,14 é float.", item, 1, []) is None
    assert feedback.verificar_explicacao("O valor 2,71 é float.", item, 1, []) is not None


@pytest.mark.parametrize("texto", [
    "A explicação verificada diz que o range para antes do limite.",
    "Segundo os trechos, o range para antes do limite.",
    "O trecho 2 mostra que o range para antes do limite.",
    "Como diz o material, o range para antes do limite.",
    "Pelo trecho do material, o range para antes do limite.",
    "No material fornecido, o range para antes do limite.",
    "Conforme o prompt, o range para antes do limite.",
    "Pelas informações acima, o range para antes do limite.",
])
def test_guarda_descarta_vazamento_do_prompt(texto):
    motivo = verificar(texto)
    assert motivo and "referência ao prompt" in motivo


def test_guarda_aceita_termo_que_esta_no_proprio_item():
    item = {**ITEM_RANGE, "enunciado": "O que faz o trecho de código abaixo?"}
    assert feedback.verificar_explicacao("O trecho repete até o limite.", item, 1, []) is None
    assert feedback.verificar_explicacao("O trecho repete até o limite.", ITEM_RANGE, 1, []) is not None


def test_guarda_aceita_bloco_vocabulario_de_programacao():
    assert verificar("O break sai do laço sem executar o resto do bloco.") is None


def item_do_banco(item_id: str) -> dict:
    return next(i for i in carregar_itens() if i["id"] == item_id)


def test_guarda_aceita_texto_real_de_repeticao_n2b():
    # texto do LLM que a versão anterior da guarda barrava só por "bloco"
    texto = ("O comando `break` sai do laço imediatamente, interrompendo a execução do resto do bloco. "
             "Isso é útil quando você quer interromper o laço em um momento específico, como quando "
             "um condição é atendida.")
    item = item_do_banco("repeticao_n2b")
    assert feedback.verificar_explicacao(texto, item, 3, []) is None


def test_guarda_descarta_contradicao_interna_real_de_condicionais_n3a():
    texto = ("A ordem das condições importa porque as avaliações são feitas de cima para baixo. "
             "A primeira condição verdadeira é executada, e as restantes são ignoradas. Por isso, a "
             "resposta \"ótimo\" é incorreta, pois a nota 9.5 é maior que 7, mas a condição "
             "\"nota >= 9\" é verdadeira, então o código imprime \"ótimo\" corretamente.")
    item = item_do_banco("condicionais_n3a")
    motivo = feedback.verificar_explicacao(texto, item, 0, [])
    assert motivo and motivo.startswith("contradição interna") and "ótimo" in motivo


@pytest.mark.parametrize("texto", [
    "A alternativa C) é incorreta. A alternativa A) está correta porque range para antes do limite.",
    "A resposta \"3\" é errada; o laço termina corretamente antes do limite.",
    "O código roda corretamente e mostra 0, 1 e 2.",
])
def test_contradicao_interna_exige_o_mesmo_sujeito(texto):
    assert verificar(texto) is None


@pytest.mark.parametrize("texto", [
    "A alternativa B) é incorreta, porque o range para antes. Mesmo assim, B) está correta.",
    "O valor \"0 1 2 3\" está errado, pois o 3 não entra. Ainda assim, \"0 1 2 3\" está correto.",
])
def test_contradicao_interna_com_letra_ou_aspas(texto):
    motivo = verificar(texto)
    assert motivo and motivo.startswith("contradição interna")


@pytest.mark.parametrize("texto, indice", [
    ("Você acertou, o range para antes do limite.", 1),         # veredito: errou
    ("Sua resposta está correta: o range para antes do limite.", 1),
    ("Parabéns! O range para antes do limite.", 1),
    ("Você errou, mas o range para antes do limite.", 0),       # veredito: acertou
    ("Você não acertou: o range para antes do limite.", 0),
    ("Sua escolha foi incorreta, o range para antes do limite.", 0),
])
def test_guarda_descarta_contradicao_com_veredito(texto, indice):
    motivo = verificar(texto, indice)
    assert motivo and "contradiz o veredito" in motivo


def test_guarda_nao_barra_afirmacao_coerente_com_o_veredito():
    assert verificar("Você errou porque o range para antes do limite.", 1) is None
    assert verificar("Você acertou: o range para antes do limite.", 0) is None


@pytest.mark.parametrize("resposta_llm, motivo", [
    ("O laço roda 7 vezes.", "número"),
    ("Conforme a explicação verificada, range(3) para antes do 3.", "referência ao prompt"),
    ("Você acertou: range(3) para antes do 3.", "contradiz o veredito"),
])
def test_gerar_feedback_descartado_pela_guarda_usa_item_sem_fonte(monkeypatch, resposta_llm, motivo):
    mockar(monkeypatch, [TRECHO_RANGE], resposta_llm)
    resultado = feedback.gerar_feedback(ITEM_RANGE, 1, ["mat_r.txt"])
    assert (resultado.explicacao, resultado.fontes, resultado.origem) == (ITEM_RANGE["explicacao"], [], "guarda")
    assert motivo in resultado.motivo_descarte
    assert resultado.explicacao_descartada == resposta_llm
    assert resultado.veredito == "Você marcou: B) 1 2 3. A resposta correta é: A) 0 1 2."


def test_gerar_feedback_aprovado_pela_guarda_mantem_llm_e_fonte(monkeypatch):
    mockar(monkeypatch, [TRECHO_RANGE], "O range(3) para antes do 3. Por isso aparecem 0, 1 e 2.")
    resultado = feedback.gerar_feedback(ITEM_RANGE, 1, ["mat_r.txt"])
    assert resultado.origem == "LLM" and resultado.fontes == ["mat_r.txt"]
    assert resultado.explicacao == "O range(3) para antes do 3. Por isso aparecem 0, 1 e 2."
    assert resultado.motivo_descarte == ""


def test_sem_modo_usa_o_da_config(monkeypatch):
    _, prompts = mockar(monkeypatch, [TRECHO])
    monkeypatch.setattr(feedback, "TUTOR_MODO_FEEDBACK", "ancorado")
    feedback.gerar_feedback(ITENS[0], 0, ["mat_c.txt"])
    monkeypatch.setattr(feedback, "TUTOR_MODO_FEEDBACK", "livre")
    feedback.gerar_feedback(ITENS[0], 0, ["mat_c.txt"])
    assert "RESULTADO (já mostrado" in prompts[0][0] and "RESULTADO (já mostrado" not in prompts[1][0]


def test_config_padrao_do_modo_e_ancorado(monkeypatch):
    import importlib
    import tia.core.config as config
    for nome in ("TUTOR_MODO_FEEDBACK", "TUTOR_TEMPERATURA", "TUTOR_TOP_P", "TUTOR_SEED"):
        monkeypatch.delenv(nome, raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    try:
        recarregado = importlib.reload(config)
        assert recarregado.TUTOR_MODO_FEEDBACK == "ancorado"
        assert (recarregado.TUTOR_TEMPERATURA, recarregado.TUTOR_TOP_P, recarregado.TUTOR_SEED) == (0.2, 0.9, 42)
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_modo_livre_mantem_prompt_antigo_sem_explicacao_do_item(monkeypatch):
    _, prompts = mockar(monkeypatch, [TRECHO])
    feedback.gerar_feedback(ITENS[0], 0, ["mat_c.txt"], modo="livre")
    assert "Explicação de n1a." not in prompts[0][0] and TRECHO["texto"] in prompts[0][0]


def test_modo_ancorado_sem_trecho_usa_fallback_sem_chamar_llm(monkeypatch):
    _, prompts = mockar(monkeypatch, [])
    assert feedback.gerar_feedback(ITENS[0], 0, ["mat_c.txt"], modo="ancorado") == FALLBACK
    assert prompts == []


def test_modo_invalido_e_rejeitado(monkeypatch):
    mockar(monkeypatch, [TRECHO])
    with pytest.raises(ValueError):
        feedback.gerar_feedback(ITENS[0], 0, ["mat_c.txt"], modo="criativo")


def test_limpar_explicacao_nao_corta_numero_decimal():
    assert feedback.limpar_explicacao("O valor 3.14 é float. Fim. Mais. Sobra.") == "O valor 3.14 é float. Fim. Mais."


def test_limpar_explicacao_descarta_frase_cortada_pelo_limite_de_tokens():
    assert feedback.limpar_explicacao("Frase completa. Frase cortada no me") == "Frase completa."
    assert feedback.limpar_explicacao("Só um pedaço sem fim") == ""  # vira texto do item


# --- banco de itens da base pedagógica (1.2.5) em conteudo/ ---

def test_banco_de_itens_e_consistente():
    itens = carregar_itens()
    ementa = carregar_ementa()
    ids_ementa = {c["id"] for c in ementa}
    assert len({i["id"] for i in itens}) == len(itens) == 120
    for i in itens:
        assert i["competencia_id"] in ids_ementa
        assert len(i["alternativas"]) == 4 and len(set(i["alternativas"])) == 4
        assert 0 <= i["indice_correto"] < 4
        assert i["explicacao"].strip()
        assert i["uso"] in ("diagnostico", "tutoria")
    def do_nivel(cid, nivel):
        return [i for i in itens if i["competencia_id"] == cid and i["nivel"] == nivel]
    # tópicos do piloto: 7 por nível (1 de diagnóstico + 6 de tutoria); base comum: 2 por nível
    for c in ementa:
        esperado = 7 if c["no_piloto"] else 2 if c["trilha"] == "base_comum" else 0
        for nivel in (1, 2, 3):
            assert len(do_nivel(c["id"], nivel)) == esperado, (c["id"], nivel)
            if esperado:
                assert sum(i["uso"] == "diagnostico" for i in do_nivel(c["id"], nivel)) == 1
    # o banco real permite concluir cada competência acertando tudo. Asserção FORTE (restaurada em
    # 15/10/2026): onde há itens suficientes para subir e dominar (TUTOR_ACERTOS_SUBIR nos níveis 1
    # e 2, TUTOR_ACERTOS_CONCLUIR no 3, sem contar os do diagnóstico, que o aluno já viu), a
    # conclusão é por DOMÍNIO. Nos outros (base comum, 2 por nível), só pelo fim dos itens: a
    # sessão termina com ressalvas e quem decide o avanço é a R1 (ORQ_ACERTO_MIN_AVANCO).
    def tutoria(cid, nivel):
        return [i for i in do_nivel(cid, nivel) if i["uso"] == "tutoria"]
    por_dominio = []
    for competencia_id in {i["competencia_id"] for i in itens}:  # só os tópicos que têm itens
        do_diagnostico = {i["id"] for i in itens if i["competencia_id"] == competencia_id
                          and i["uso"] == "diagnostico"}
        suficiente = (len(tutoria(competencia_id, 1)) >= adaptativo.acertos_para_subir()
                      and len(tutoria(competencia_id, 2)) >= adaptativo.acertos_para_subir()
                      and len(tutoria(competencia_id, 3)) >= adaptativo.acertos_para_concluir())
        estado = iniciar(itens, competencia_id, evitar=do_diagnostico)
        for _ in range(len(itens)):
            if estado.concluida:
                break
            estado = adaptativo.avancar(estado, itens, True, do_diagnostico)
        assert estado.concluida, competencia_id
        if suficiente:
            por_dominio.append(competencia_id)
            assert not estado.com_ressalvas, competencia_id
            assert estado.acertos_seguidos_nivel_max == adaptativo.acertos_para_concluir(), competencia_id
            assert not set(estado.itens_usados) & do_diagnostico, competencia_id
        else:
            assert estado.com_ressalvas, competencia_id
    assert sorted(por_dominio) == ["cib_01", "cib_02", "dev_01", "dev_02"]


# Itens revisados pela Pessoa 4 (1.2.5 e 1.5.2). Revisão concluída em 19/10/2026: os 120 itens do banco
# (84 gerados por LLM local e 36 da base comum) foram validados. Item novo ou alterado só entra na lista
# depois de revisado, e o status no itens.json só vira "validado" para ids desta lista.
VALIDADOS_PELA_PESSOA_4: set[str] = {
    "cib_01_n1_001", "cib_01_n1_002", "cib_01_n1_003", "cib_01_n1_004", "cib_01_n1_005", "cib_01_n1_006",
    "cib_01_n1_007", "cib_01_n2_001", "cib_01_n2_002", "cib_01_n2_003", "cib_01_n2_004", "cib_01_n2_005",
    "cib_01_n2_006", "cib_01_n2_007", "cib_01_n3_001", "cib_01_n3_002", "cib_01_n3_003", "cib_01_n3_004",
    "cib_01_n3_005", "cib_01_n3_006", "cib_01_n3_007", "cib_02_n1_001", "cib_02_n1_002", "cib_02_n1_003",
    "cib_02_n1_004", "cib_02_n1_005", "cib_02_n1_006", "cib_02_n1_007", "cib_02_n2_001", "cib_02_n2_002",
    "cib_02_n2_003", "cib_02_n2_004", "cib_02_n2_005", "cib_02_n2_006", "cib_02_n2_007", "cib_02_n3_001",
    "cib_02_n3_002", "cib_02_n3_003", "cib_02_n3_004", "cib_02_n3_005", "cib_02_n3_006", "cib_02_n3_007",
    "condicionais_n1a", "condicionais_n1b", "condicionais_n2a", "condicionais_n2b", "condicionais_n3a",
    "condicionais_n3b", "dev_01_n1_001", "dev_01_n1_002", "dev_01_n1_003", "dev_01_n1_004", "dev_01_n1_005",
    "dev_01_n1_006", "dev_01_n1_007", "dev_01_n2_001", "dev_01_n2_002", "dev_01_n2_003", "dev_01_n2_004",
    "dev_01_n2_005", "dev_01_n2_006", "dev_01_n2_007", "dev_01_n3_001", "dev_01_n3_002", "dev_01_n3_003",
    "dev_01_n3_004", "dev_01_n3_005", "dev_01_n3_006", "dev_01_n3_007", "dev_02_n1_001", "dev_02_n1_002",
    "dev_02_n1_003", "dev_02_n1_004", "dev_02_n1_005", "dev_02_n1_006", "dev_02_n1_007", "dev_02_n2_001",
    "dev_02_n2_002", "dev_02_n2_003", "dev_02_n2_004", "dev_02_n2_005", "dev_02_n2_006", "dev_02_n2_007",
    "dev_02_n3_001", "dev_02_n3_002", "dev_02_n3_003", "dev_02_n3_004", "dev_02_n3_005", "dev_02_n3_006",
    "dev_02_n3_007", "funcoes_n1a", "funcoes_n1b", "funcoes_n2a", "funcoes_n2b", "funcoes_n3a",
    "funcoes_n3b", "listas_strings_n1a", "listas_strings_n1b", "listas_strings_n2a", "listas_strings_n2b",
    "listas_strings_n3a", "listas_strings_n3b", "recursao_n1a", "recursao_n1b", "recursao_n2a",
    "recursao_n2b", "recursao_n3a", "recursao_n3b", "repeticao_n1a", "repeticao_n1b", "repeticao_n2a",
    "repeticao_n2b", "repeticao_n3a", "repeticao_n3b", "variaveis_tipos_n1a", "variaveis_tipos_n1b",
    "variaveis_tipos_n2a", "variaveis_tipos_n2b", "variaveis_tipos_n3a", "variaveis_tipos_n3b",
}


def test_status_validado_so_para_itens_revisados_pela_pessoa_4():
    itens = carregar_itens()
    gerados = [i for i in itens if i.get("origem") == "llm"]
    assert len(gerados) == 84  # dev_01, dev_02, cib_01, cib_02
    assert VALIDADOS_PELA_PESSOA_4 <= {i["id"] for i in itens}
    for i in itens:
        if i["id"] in VALIDADOS_PELA_PESSOA_4:
            assert i["status"] == "validado", i["id"]
        else:
            assert i["status"].startswith("rascunho"), f"{i['id']}: item fora da lista da Pessoa 4 deve ser rascunho"


# --- banco ---

def test_migracao_do_historico_preserva_linhas_antigas(tmp_path, monkeypatch):
    caminho = str(tmp_path / "antigo.db")
    conexao = sqlite3.connect(caminho)
    conexao.execute("""CREATE TABLE historico_respostas (id INTEGER PRIMARY KEY AUTOINCREMENT,
                       aluno_id TEXT, topico TEXT, dificuldade TEXT, acertou BOOLEAN, timestamp DATETIME)""")
    conexao.execute("INSERT INTO historico_respostas (aluno_id, topico, acertou) VALUES ('X1', 'antigo', 1)")
    conexao.commit()
    conexao.close()

    monkeypatch.setattr(database, "DB_PATH", caminho)
    database.criar_tabelas()
    database.criar_tabelas()  # idempotente

    conexao = sqlite3.connect(caminho)
    colunas = {linha[1] for linha in conexao.execute("PRAGMA table_info(historico_respostas)")}
    assert set(database.COLUNAS_NOVAS_HISTORICO) <= colunas
    assert {"item_id", "sessao_id"} <= colunas
    # a linha antiga continua lá, com as colunas novas em NULL
    assert conexao.execute("SELECT topico, acertou, item_id, sessao_id FROM historico_respostas").fetchall() == [
        ("antigo", 1, None, None)]
    conexao.close()


# --- relatório de comparação dos modos (sem LLM) ---

def test_relatorio_de_comparacao_tem_os_dois_modos_e_campo_do_revisor():
    from datetime import date

    from tia.agentes.tutor.comparar_modos import formatar_relatorio

    saida = {"explicacao": "Use a | b.", "fontes": ["mat_c.txt"], "origem": "LLM", "tempo_s": 1.0,
             "motivo_descarte": "", "explicacao_descartada": ""}
    resultados = [{"item": ITENS[0], "indice_marcado": 2,
                   "saidas": {"ancorado": saida, "livre": {**saida, "fontes": [], "origem": "fallback"}}}]
    texto = formatar_relatorio(resultados, date(2026, 10, 10))

    assert "| | Modo ancorado | Modo livre |" in texto
    assert "Use a \\| b." in texto  # barra escapada não quebra a tabela
    assert "**Resposta marcada pelo aluno:** C) c" in texto and "**Gabarito:** B) b" in texto
    assert "**Explicação verificada (banco de itens):** Explicação de n1a." in texto
    assert "**Avaliação do revisor:**" in texto
    assert "**Veredito (fixo, gerado por código):** Você marcou: C) c. A resposta correta é: B) b." in texto
    assert "Ancorado: 1 do LLM, 0 guarda, 0 fallback. Livre: 0 do LLM, 0 guarda, 1 fallback." in texto
    assert "Motivo do descarte" not in texto


def test_relatorio_so_ancorado_mostra_origem_guarda_e_total_de_descartes():
    from datetime import date

    from tia.agentes.tutor.comparar_modos import formatar_relatorio

    boa = {"explicacao": "Texto bom.", "fontes": ["mat_c.txt"], "origem": "LLM", "tempo_s": 1.0,
           "motivo_descarte": "", "explicacao_descartada": ""}
    barrada = {"explicacao": "Explicação de n1b.", "fontes": [], "origem": "guarda", "tempo_s": 1.0,
               "motivo_descarte": "número inventado: 7", "explicacao_descartada": "Roda 7 vezes."}
    resultados = [{"item": ITENS[0], "indice_marcado": 2, "saidas": {"ancorado": boa}},
                  {"item": ITENS[1], "indice_marcado": 2, "saidas": {"ancorado": barrada}}]
    texto = formatar_relatorio(resultados, date(2026, 10, 10))

    assert "| | Modo ancorado |" in texto and "Modo livre" not in texto
    assert "Ancorado: 1 do LLM, 1 guarda, 0 fallback." in texto
    assert "**Total de descartes pela guarda:** ancorado 1." in texto
    assert "| Motivo do descarte | número inventado: 7 |" in texto
    assert "| Texto do LLM descartado | Roda 7 vezes. |" in texto
