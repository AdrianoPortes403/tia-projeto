"""
Configuração central do Sistema TIA.

Toda configuração do projeto vem daqui, lida de variáveis de ambiente
(arquivo .env na raiz, carregado com python-dotenv) com valor padrão.
Os demais módulos importam as constantes deste arquivo; nenhum outro
lugar deve chamar os.getenv.

Como conferir os valores em uso:
    python -m tia.core.config

Pré-requisitos:
    - .env na raiz (copiar de .env.example); sem ele, valem os padrões abaixo.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# --- LLM local (Ollama) — requisito R07: nunca API externa ---
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
CHAT_MODEL = os.getenv("CHAT_MODEL", "qwen3:1.7b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
# Quanto tempo o Ollama mantém o modelo carregado após a última chamada
# (evita recarregar a cada interação, o que estouraria o R09)
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")

# --- Banco de dados (SQLite) ---
DB_PATH = os.getenv("DB_PATH", "data/tia.db")

# --- RAG ---
# Pasta com os arquivos .txt do material do curso
MATERIAIS_DIR = os.getenv("MATERIAIS_DIR", "conteudo/materiais")
# Pasta onde o Chroma guarda o índice vetorial (persistente entre execuções)
CHROMA_DIR = os.getenv("CHROMA_DIR", "data/chroma_db")
# Nome da "coleção" dentro do Chroma (como uma tabela, dentro do banco vetorial)
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "material_curso")
# Tamanho de cada pedaço (chunk) de texto indexado, em caracteres
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
# Sobreposição entre pedaços consecutivos, para não cortar uma ideia ao meio
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))

# --- Agente 1 (Planejador) ---
# Arquivos de conteúdo pedagógico (PROVISÓRIOS até a entrega da Pessoa 4)
EMENTA_PATH = os.getenv("EMENTA_PATH", "conteudo/ementa/ementa.json")
PERFIS_PATH = os.getenv("PERFIS_PATH", "conteudo/perfis/perfis.json")
# Tempo máximo (s) para o LLM escrever as justificativas; abaixo do limite de 15 s do R09
# Decisão de 10/10 (CLAUDE.md): alto em desenvolvimento; o R09 será medido na VM.
# Com 12 s, as justificativas estouravam em CPU (ReadTimeout) e caíam no texto padrão.
PLANEJADOR_TIMEOUT_LLM = int(os.getenv("PLANEJADOR_TIMEOUT_LLM", "120"))

# --- Agente 2 (Tutor) ---
# Banco de itens do questionário (PROVISÓRIO até a entrega da Pessoa 4)
BANCO_ITENS_PATH = os.getenv("BANCO_ITENS_PATH", "conteudo/banco_itens/itens.json")
# Decisão de 10/10 (CLAUDE.md): não otimizar para os 15 s do R09 em desenvolvimento;
# o LLM de produção roda em máquina mais potente. O R09 será medido na VM.
# Tempo máximo (s) de espera pelo LLM no feedback; alto em desenvolvimento.
TUTOR_TIMEOUT_LLM = int(os.getenv("TUTOR_TIMEOUT_LLM", "120"))
# Limite de tokens gerados no feedback: folga para até 3 frases completas, de
# modo que o descarte de frase cortada (feedback.limpar_explicacao) seja raro.
TUTOR_MAX_TOKENS = int(os.getenv("TUTOR_MAX_TOKENS", "200"))
# Amostragem do LLM só nas chamadas de FEEDBACK do Tutor (options.temperature,
# options.top_p e options.seed do Ollama). Temperatura baixa e seed fixa deixam
# o feedback estável entre execuções: o mesmo item e a mesma resposta tendem a
# gerar o mesmo texto, que pode ser revisado. As outras chamadas (Planejador,
# demo do RAG) continuam com o padrão do Ollama.
TUTOR_TEMPERATURA = float(os.getenv("TUTOR_TEMPERATURA", "0.2"))
TUTOR_TOP_P = float(os.getenv("TUTOR_TOP_P", "0.9"))
TUTOR_SEED = int(os.getenv("TUTOR_SEED", "42"))
# Como o LLM escreve o feedback:
#   "ancorado" (padrão): reformula a explicação verificada do item, apoiada nos
#              trechos do RAG; proibido calcular ou inventar valores e resultados;
#   "livre":   explica só a partir dos trechos (modo antigo, mantido para comparação).
TUTOR_MODO_FEEDBACK = os.getenv("TUTOR_MODO_FEEDBACK", "ancorado")
# Quantos trechos do material o RAG busca para o prompt do feedback.
TUTOR_NUM_TRECHOS = int(os.getenv("TUTOR_NUM_TRECHOS", "4"))
# Distância máxima (Chroma, L2 ao quadrado com nomic-embed-text) para um trecho
# contar como relevante; medido no material de exemplo: relevantes ~200-330,
# sem relação ~440+. Rever se trocar o modelo de embedding.
# PROVISÓRIO: calibrado com o material PROVISÓRIO (conteudo/materiais/provisorio_*.txt).
# Recalibrar quando o material real do curso (Pessoa 4) chegar: medir as
# distâncias de trechos relevantes e sem relação e ajustar este valor.
TUTOR_DISTANCIA_MAXIMA = float(os.getenv("TUTOR_DISTANCIA_MAXIMA", "400"))

# Portão de cobertura do diálogo do Tutor: fração mínima dos termos de conteúdo
# da pergunta (sem stopwords nem termos genéricos do índice) que precisa aparecer
# nos trechos recuperados para o LLM ser chamado. A distância do RAG sozinha não
# separa pergunta coberta de pergunta fora do material (medido em 10/10).
# Ajustar só com o conjunto de ajuste: python -m tia.agentes.tutor.avaliar_dialogo
# 0.42: meio do intervalo ótimo no ajuste (0.35 a 0.50: nenhuma pergunta "fora"
# passa e as 9 cobertas passam), medido em 10/10 com o material PROVISÓRIO.
TUTOR_COBERTURA_MIN = float(os.getenv("TUTOR_COBERTURA_MIN", "0.42"))
# Regra adicional do portão: o termo de conteúdo mais raro da pergunta no índice
# (maior IDF, contando sinônimos) precisa estar nos trechos recuperados.
TUTOR_EXIGE_TERMO_RARO = os.getenv("TUTOR_EXIGE_TERMO_RARO", "0").lower() in ("1", "true", "sim")
# Dias sem interação com o Tutor (respostas, sessões, diálogo) a partir dos
# quais o aluno conta como inativo e recebe o incentivo (GET /tutor/incentivo).
INATIVIDADE_DIAS = int(os.getenv("INATIVIDADE_DIAS", "3"))

# --- Agente 3 (Relatório) ---
# LGPD (R08): o relatório da turma/instituição não mostra grupo com menos de
# RELATORIO_MIN_GRUPO alunos (nem contagem de alunos abaixo disso).
RELATORIO_MIN_GRUPO = int(os.getenv("RELATORIO_MIN_GRUPO", "5"))
# O LLM só redige o parágrafo de interpretação; os números são calculados por código.
RELATORIO_TIMEOUT_LLM = int(os.getenv("RELATORIO_TIMEOUT_LLM", "120"))
RELATORIO_MAX_TOKENS = int(os.getenv("RELATORIO_MAX_TOKENS", "250"))
RELATORIO_TEMPERATURA = float(os.getenv("RELATORIO_TEMPERATURA", "0.2"))
RELATORIO_SEED = int(os.getenv("RELATORIO_SEED", "42"))
# Tendência do acerto (indicador 2 e regra de queda do orquestrador). PROVISÓRIO.
# Sem sessao_id: últimas RELATORIO_TENDENCIA_JANELA respostas x anteriores.
RELATORIO_TENDENCIA_JANELA = int(os.getenv("RELATORIO_TENDENCIA_JANELA", "5"))
# Mínimo de respostas em cada lado da comparação para haver tendência.
RELATORIO_TENDENCIA_MIN_RESPOSTAS = int(os.getenv("RELATORIO_TENDENCIA_MIN_RESPOSTAS", "3"))
# Variação da taxa de acerto que conta como subida/queda (0.15 = 15 pontos).
RELATORIO_TENDENCIA_LIMIAR = float(os.getenv("RELATORIO_TENDENCIA_LIMIAR", "0.15"))

# --- Orquestração (EAP 1.3.5): regras (docs/arquitetura/arquitetura.md, "Decisões de orquestração") ---
# Queda (R2, PROVISÓRIO): depois de um reforço por queda, só reforça de novo após
# pelo menos estas respostas novas (além de no máximo um reforço por sessão).
ORQ_QUEDA_RESPOSTAS_ENTRE_REPLANOS = int(os.getenv("ORQ_QUEDA_RESPOSTAS_ENTRE_REPLANOS", "5"))
# Inatividade (R3, PROVISÓRIO): a partir de INATIVIDADE_DIAS (acima), só incentivo,
# sem refazer a trilha; a trilha só é refeita a partir de ORQ_INATIVIDADE_REFAZER_DIAS.
ORQ_INATIVIDADE_REFAZER_DIAS = int(os.getenv("ORQ_INATIVIDADE_REFAZER_DIAS", "14"))

# --- Painel do docente (EAP 1.4.5) ---
# Alerta de desempenho baixo: taxa de acerto geral abaixo deste valor, desde que o
# aluno tenha pelo menos PAINEL_MIN_RESPOSTAS respostas. PROVISÓRIO (Pessoa 4).
PAINEL_DESEMPENHO_BAIXO = float(os.getenv("PAINEL_DESEMPENHO_BAIXO", "0.5"))
PAINEL_MIN_RESPOSTAS = int(os.getenv("PAINEL_MIN_RESPOSTAS", "5"))


if __name__ == "__main__":
    for nome in ("OLLAMA_URL", "CHAT_MODEL", "EMBED_MODEL", "OLLAMA_KEEP_ALIVE", "DB_PATH",
                 "MATERIAIS_DIR", "CHROMA_DIR", "COLLECTION_NAME",
                 "CHUNK_SIZE", "CHUNK_OVERLAP", "EMENTA_PATH", "PERFIS_PATH",
                 "PLANEJADOR_TIMEOUT_LLM", "BANCO_ITENS_PATH", "TUTOR_TIMEOUT_LLM", "TUTOR_MAX_TOKENS", "TUTOR_TEMPERATURA", "TUTOR_TOP_P", "TUTOR_SEED", "TUTOR_MODO_FEEDBACK",
                 "TUTOR_NUM_TRECHOS",
                 "TUTOR_DISTANCIA_MAXIMA", "TUTOR_COBERTURA_MIN", "TUTOR_EXIGE_TERMO_RARO",
                 "INATIVIDADE_DIAS", "RELATORIO_MIN_GRUPO", "RELATORIO_TIMEOUT_LLM", "RELATORIO_MAX_TOKENS",
                 "RELATORIO_TEMPERATURA", "RELATORIO_SEED", "RELATORIO_TENDENCIA_JANELA",
                 "RELATORIO_TENDENCIA_MIN_RESPOSTAS", "RELATORIO_TENDENCIA_LIMIAR",
                 "ORQ_QUEDA_RESPOSTAS_ENTRE_REPLANOS", "ORQ_INATIVIDADE_REFAZER_DIAS",
                 "PAINEL_DESEMPENHO_BAIXO", "PAINEL_MIN_RESPOSTAS"):
        print(f"{nome} = {globals()[nome]}")
