"""
Testes do Agente 1 (Planejador): lógica determinística, justificativas
(com o llm_client mockado) e migração da tabela trilha_estudo.

Como rodar:
    ./run_tests.sh tests/test_planejador.py
"""

import json
import os
import sqlite3

import pytest
import requests

import tia.agentes.planejador.justificar as justificar
import tia.core.database as database
from tia.agentes.planejador.justificar import justificar_trilha
from tia.agentes.planejador.modelos import EntradaPlanejador
from tia.agentes.planejador.planejar import (
    CicloPrerequisitos, CompetenciaInexistente, PerfilInexistente,
    carregar_ementa, carregar_perfis, gerar_trilha,
)
from tia.core.config import MATERIAIS_DIR

# Ementa de teste fora de ordem de propósito: c depende de b, b de a.
EMENTA = [
    {"id": "c", "nome": "C", "horas_estimadas": 4, "prerequisitos": ["b"], "materiais": []},
    {"id": "a", "nome": "A", "horas_estimadas": 4, "prerequisitos": [], "materiais": ["a.txt"]},
    {"id": "b", "nome": "B", "horas_estimadas": 4, "prerequisitos": ["a"], "materiais": []},
    {"id": "d", "nome": "D", "horas_estimadas": 2, "prerequisitos": ["a"], "materiais": []},
]
PERFIS = [
    {"id": "base", "nome": "Base", "ritmo": 1.0, "competencias_dispensaveis": {"a": 0.8}},
    {"id": "lento", "nome": "Lento", "ritmo": 1.5, "competencias_dispensaveis": {}},
]


def entrada(**campos) -> EntradaPlanejador:
    dados = {"aluno_id": "T-001", "perfil_id": "base", "diagnostico": {}, "horas_semanais": 6}
    dados.update(campos)
    return EntradaPlanejador(**dados)


def ids(trilha) -> list[str]:
    return [e.competencia_id for e in trilha.etapas]


# --- lógica determinística ---

def test_trilha_respeita_prerequisitos():
    trilha = gerar_trilha(entrada(), EMENTA, PERFIS)
    ordem = ids(trilha)
    assert ordem == ["a", "b", "c", "d"]  # empate (b, d) desfeito pela ordem da ementa
    for competencia in EMENTA:
        for pre in competencia["prerequisitos"]:
            assert ordem.index(pre) < ordem.index(competencia["id"])
    assert [e.ordem for e in trilha.etapas] == [1, 2, 3, 4]


def test_pula_competencia_dispensavel():
    trilha = gerar_trilha(entrada(diagnostico={"a": 0.8}), EMENTA, PERFIS)
    assert "a" not in ids(trilha)
    assert ids(trilha) == ["b", "c", "d"]  # dependentes de "a" continuam na trilha


def test_nao_pula_abaixo_do_limiar_nem_fora_do_perfil():
    assert "a" in ids(gerar_trilha(entrada(diagnostico={"a": 0.79}), EMENTA, PERFIS))
    # "b" não está em competencias_dispensaveis: nota máxima não basta
    assert "b" in ids(gerar_trilha(entrada(diagnostico={"b": 1.0}), EMENTA, PERFIS))


def test_detecta_ciclo():
    ementa_ciclica = [
        {"id": "x", "nome": "X", "horas_estimadas": 1, "prerequisitos": ["z"]},
        {"id": "y", "nome": "Y", "horas_estimadas": 1, "prerequisitos": ["x"]},
        {"id": "z", "nome": "Z", "horas_estimadas": 1, "prerequisitos": ["y"]},
    ]
    with pytest.raises(CicloPrerequisitos, match="x, y, z"):
        gerar_trilha(entrada(), ementa_ciclica, PERFIS)


def test_erro_claro_para_perfil_ou_competencia_inexistente():
    with pytest.raises(PerfilInexistente, match="avancado"):
        gerar_trilha(entrada(perfil_id="avancado"), EMENTA, PERFIS)
    with pytest.raises(CompetenciaInexistente, match="zzz"):
        gerar_trilha(entrada(diagnostico={"zzz": 0.5}), EMENTA, PERFIS)
    ementa_quebrada = [{"id": "a", "nome": "A", "horas_estimadas": 1, "prerequisitos": ["fantasma"]}]
    with pytest.raises(CompetenciaInexistente, match="fantasma"):
        gerar_trilha(entrada(), ementa_quebrada, PERFIS)


def test_distribui_semanas_e_aplica_ritmo():
    # ritmo 1.5: a=6h, b=6h, c=6h, d=3h; 6 h/semana -> semanas 1, 2, 3, 4
    trilha = gerar_trilha(entrada(perfil_id="lento"), EMENTA, PERFIS)
    assert [e.horas for e in trilha.etapas] == [6.0, 6.0, 6.0, 3.0]
    assert [e.semana_inicio for e in trilha.etapas] == [1, 2, 3, 4]
    # com 10 h/semana: acumulado antes de cada etapa 0, 6, 12, 18 -> semanas 1, 1, 2, 2
    trilha = gerar_trilha(entrada(perfil_id="lento", horas_semanais=10), EMENTA, PERFIS)
    assert [e.semana_inicio for e in trilha.etapas] == [1, 1, 2, 2]


def test_e_deterministica():
    e = entrada(diagnostico={"a": 0.3, "b": 0.6})
    assert gerar_trilha(e, EMENTA, PERFIS) == gerar_trilha(e, EMENTA, PERFIS)


def test_entrada_recusa_nome_como_aluno_id_e_nota_fora_da_faixa():
    with pytest.raises(ValueError):
        entrada(aluno_id="João da Silva")
    with pytest.raises(ValueError):
        entrada(diagnostico={"a": 1.5})


# --- conteúdo PROVISÓRIO em conteudo/ ---

def test_conteudo_provisorio_e_consistente():
    for caminho in ("conteudo/ementa/ementa.json", "conteudo/perfis/perfis.json"):
        with open(caminho, encoding="utf-8") as arquivo:
            assert json.load(arquivo)["_provisorio"] is True
    ementa, perfis = carregar_ementa(), carregar_perfis()
    assert len(ementa) == 6
    assert {p["id"] for p in perfis} == {"iniciante", "intermediario"}
    for competencia in ementa:
        for material in competencia["materiais"]:
            assert os.path.exists(os.path.join(MATERIAIS_DIR, material)), material
    for perfil in perfis:  # gera sem ciclo nem erro com os arquivos reais
        assert gerar_trilha(entrada(perfil_id=perfil["id"])).etapas


# --- replanejamento incremental (competências concluídas) ---

def pendentes(trilha) -> list[str]:
    return [e.competencia_id for e in trilha.etapas if not e.concluida]


def test_replanejamento_reduz_a_trilha_ao_que_falta():
    completa = gerar_trilha(entrada(), EMENTA, PERFIS)
    reduzida = gerar_trilha(entrada(concluidas=["a"]), EMENTA, PERFIS)
    assert pendentes(completa) == ["a", "b", "c", "d"]
    assert pendentes(reduzida) == ["b", "c", "d"]  # só o que falta é planejado
    concluida = reduzida.etapas[0]
    assert (concluida.competencia_id, concluida.concluida, concluida.horas, concluida.semana_inicio) == ("a", True, 0, 0)
    # o que falta é agendado a partir da semana 1 (b e c: 4 h cada, 6 h/semana)
    assert [(e.competencia_id, e.semana_inicio) for e in reduzida.etapas if not e.concluida] == [
        ("b", 1), ("c", 1), ("d", 2)]


@pytest.mark.parametrize("concluidas", [["a"], ["a", "b"], ["b"], ["a", "b", "c", "d"]])
def test_replanejamento_nunca_traz_de_volta_uma_concluida(concluidas):
    # nem com nota zero no diagnóstico, nem sendo pré-requisito do que falta
    trilha = gerar_trilha(entrada(concluidas=concluidas, diagnostico={"a": 0.0}), EMENTA, PERFIS)
    assert not set(concluidas) & set(pendentes(trilha))
    assert {e.competencia_id for e in trilha.etapas if e.concluida} == set(concluidas)


def test_concluida_conta_como_prerequisito_cumprido_e_a_ordem_se_mantem():
    trilha = gerar_trilha(entrada(concluidas=["b"]), EMENTA, PERFIS)
    assert ids(trilha) == ["a", "b", "c", "d"]  # mesma ordem topológica
    assert pendentes(trilha) == ["a", "c", "d"]


def test_concluida_dispensavel_aparece_como_concluida():
    # "a" seria pulada pelo perfil (nota 0.9 >= 0.8), mas foi concluída: fica no histórico
    trilha = gerar_trilha(entrada(diagnostico={"a": 0.9}, concluidas=["a"]), EMENTA, PERFIS)
    assert trilha.etapas[0].competencia_id == "a" and trilha.etapas[0].concluida


def test_concluida_fora_da_ementa_e_recusada():
    with pytest.raises(CompetenciaInexistente):
        gerar_trilha(entrada(concluidas=["z"]), EMENTA, PERFIS)


def test_justificativas_so_para_o_que_falta(monkeypatch):
    prompts = []

    def llm_falso(prompt, **kwargs):
        prompts.append(prompt)
        return "1. Frase B.\n2. Frase C.\n3. Frase D."

    monkeypatch.setattr(justificar, "chamar_llm", llm_falso)
    justificada = justificar_trilha(gerar_trilha(entrada(concluidas=["a"]), EMENTA, PERFIS), {})
    assert "1. B" in prompts[0] and "A (nota" not in prompts[0]  # a concluída não vai ao LLM
    assert [(e.competencia_id, e.justificativa, e.origem_justificativa) for e in justificada.etapas] == [
        ("a", "Competência já concluída.", None), ("b", "Frase B.", "LLM"), ("c", "Frase C.", "LLM"),
        ("d", "Frase D.", "LLM")]
    assert justificada.falha_llm is None


def test_trilha_toda_concluida_nao_chama_o_llm(monkeypatch):
    monkeypatch.setattr(justificar, "chamar_llm", lambda *a, **k: pytest.fail("não devia chamar o LLM"))
    trilha = gerar_trilha(entrada(concluidas=["a", "b", "c", "d"]), EMENTA, PERFIS)
    assert justificar_trilha(trilha, {}) == trilha


# --- justificativas (llm_client mockado) ---

def test_justificativas_usam_um_unico_prompt(monkeypatch):
    chamadas = []

    def llm_falso(prompt, **kwargs):
        chamadas.append((prompt, kwargs))
        return "<think></think>\n1. Base de tudo.\n2) B: depende de A.\nlixo sem número\n3 - Fecha o ciclo."

    monkeypatch.setattr(justificar, "chamar_llm", llm_falso)
    trilha = gerar_trilha(entrada(), EMENTA, PERFIS)
    justificada = justificar_trilha(trilha, {})

    assert len(chamadas) == 1
    prompt, kwargs = chamadas[0]
    # timeout da config (decisão de 10/10: alto em desenvolvimento; R09 medido na VM)
    assert kwargs["think"] is False and kwargs["timeout"] == justificar.PLANEJADOR_TIMEOUT_LLM
    assert "T-001" not in prompt  # nenhum identificador do aluno vai ao LLM
    frases = [e.justificativa for e in justificada.etapas]
    assert frases[:3] == ["Base de tudo.", "Depende de A.", "Fecha o ciclo."]
    assert frases[3] == trilha.etapas[3].justificativa  # etapa 4 sem frase: texto padrão
    assert [e.origem_justificativa for e in justificada.etapas] == ["LLM", "LLM", "LLM", "fallback"]
    assert justificada.falha_llm == "formato"  # uma etapa ficou sem frase válida


def test_falha_do_llm_nao_bloqueia_trilha(monkeypatch):
    def llm_fora_do_ar(prompt, **kwargs):
        raise requests.Timeout("demorou")

    monkeypatch.setattr(justificar, "chamar_llm", llm_fora_do_ar)
    trilha = gerar_trilha(entrada(), EMENTA, PERFIS)
    justificada = justificar_trilha(trilha, {})
    assert [e.justificativa for e in justificada.etapas] == [e.justificativa for e in trilha.etapas]
    assert {e.origem_justificativa for e in justificada.etapas} == {"fallback"}
    assert justificada.falha_llm == "timeout"  # avisa que foi o tempo do LLM


def test_llm_justifica_tudo_sem_falha(monkeypatch):
    monkeypatch.setattr(justificar, "chamar_llm",
                        lambda prompt, **kwargs: "\n".join(f"{n}. Frase {n}." for n in range(1, 5)))
    justificada = justificar_trilha(gerar_trilha(entrada(), EMENTA, PERFIS), {})
    assert justificada.falha_llm is None and {e.origem_justificativa for e in justificada.etapas} == {"LLM"}


def test_descrever_falha():
    from tia.core.llm_client import descrever_falha
    assert descrever_falha(requests.Timeout("x")) == "timeout"
    assert descrever_falha(requests.ReadTimeout("x")) == "timeout"
    assert descrever_falha(requests.ConnectionError("x")) == "ConnectionError"


# --- banco ---

def test_migracao_preserva_linhas_antigas(tmp_path, monkeypatch):
    caminho = str(tmp_path / "antigo.db")
    conexao = sqlite3.connect(caminho)
    conexao.execute("""CREATE TABLE trilha_estudo (id INTEGER PRIMARY KEY AUTOINCREMENT,
                       aluno_id TEXT, semana INTEGER, topico TEXT, horas_previstas INTEGER)""")
    conexao.execute("INSERT INTO trilha_estudo (aluno_id, semana, topico, horas_previstas) VALUES ('X1', 1, 'antigo', 3)")
    conexao.commit()
    conexao.close()

    monkeypatch.setattr(database, "DB_PATH", caminho)
    database.criar_tabelas()
    database.criar_tabelas()  # idempotente

    conexao = sqlite3.connect(caminho)
    colunas = {linha[1] for linha in conexao.execute("PRAGMA table_info(trilha_estudo)")}
    assert set(database.COLUNAS_NOVAS_TRILHA) <= colunas
    assert conexao.execute("SELECT topico FROM trilha_estudo").fetchall() == [("antigo",)]
    conexao.close()
