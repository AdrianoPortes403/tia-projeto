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

def _lista(valor: str) -> list[str]:
    return [parte.strip() for parte in valor.split(",") if parte.strip()]


# --- LLM local (Ollama) — requisito R07: nunca API externa ---
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
# Modelos de chat que a VM baixa (deploy/modelos.sh) e mede (verificar.sh --medir-r09).
# qwen3.5:9b: etiqueta PROVISÓRIA, a confirmar com "ollama pull" na VM.
MODELOS_LLM = _lista(os.getenv("MODELOS_LLM", "qwen3:1.7b,qwen3:4b,qwen3:8b,qwen3.5:9b"))
# Modelo usado pelos agentes. CHAT_MODEL é o nome antigo, ainda aceito no .env.
MODELO_PADRAO = os.getenv("MODELO_PADRAO", os.getenv("CHAT_MODEL", "qwen3:1.7b"))
CHAT_MODEL = MODELO_PADRAO
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
# Como desligar o raciocínio ("thinking") de cada modelo, quando quem chama pede
# think=False: "padrão=modo" separados por ";", o primeiro padrão que casar
# (fnmatch) vale. Modos: "prompt" (sufixo /nothink na última mensagem),
# "api" (opção "think": false do Ollama), "prompt+api" (os dois) ou "nada".
# Os blocos de raciocínio que vierem no texto (RACIOCINIO_TAGS) são sempre
# removidos antes das guardas e dos limites de tamanho (llm_client).
# PROVISÓRIO para qwen3.5 (confirmar na VM com verificar.sh --medir-r09).
RACIOCINIO_POR_MODELO = os.getenv("RACIOCINIO_POR_MODELO", "qwen3:*=prompt+api;qwen3.5:*=api;*=nada")
RACIOCINIO_TAGS = _lista(os.getenv("RACIOCINIO_TAGS", "think,thinking,reasoning"))
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
# Arquivos de conteúdo pedagógico: base pedagógica alinhada à EAP (1.2.3 e 1.2.4),
# convertida para o formato deste repositório (base comum de Python + trilhas dev e defesa_cibernetica)
EMENTA_PATH = os.getenv("EMENTA_PATH", "conteudo/ementa/ementa.json")
PERFIS_PATH = os.getenv("PERFIS_PATH", "conteudo/perfis/perfis.json")
# Primeiro acesso (onboarding conversacional + diagnóstico, contrato 1.3.2)
ONBOARDING_USA_LLM = os.getenv("ONBOARDING_USA_LLM", "1").lower() in ("1", "true", "sim")
ONBOARDING_TIMEOUT_LLM = int(os.getenv("ONBOARDING_TIMEOUT_LLM", "60"))
# Piloto (1.5.1): prazo da matrícula em dias (0 = sem prazo) e escopo da trilha.
# No piloto de 27/10 a 04/11/2026: PILOTO_PRAZO_DIAS=8 e PILOTO_ESCOPO=piloto no .env.
PILOTO_PRAZO_DIAS = int(os.getenv("PILOTO_PRAZO_DIAS", "0"))
PILOTO_ESCOPO = os.getenv("PILOTO_ESCOPO", "completa")
# Tempo máximo (s) para o LLM escrever as justificativas; abaixo do limite de 15 s do R09
# Decisão de 10/10 (CLAUDE.md): alto em desenvolvimento; o R09 será medido na VM.
# Com 12 s, as justificativas estouravam em CPU (ReadTimeout) e caíam no texto padrão.
PLANEJADOR_TIMEOUT_LLM = int(os.getenv("PLANEJADOR_TIMEOUT_LLM", "120"))

# --- Agente 2 (Tutor) ---
# Banco de itens do questionário (base pedagógica 1.2.5; itens ainda em revisão docente)
BANCO_ITENS_PATH = os.getenv("BANCO_ITENS_PATH", "conteudo/banco_itens/itens.json")
# Avaliação adaptativa (1.2.5, seção 3): sobe de nível com N acertos seguidos, desce com
# N erros seguidos e conclui com N acertos seguidos no nível 3. A validar com a Pessoa 2.
TUTOR_ACERTOS_SUBIR = int(os.getenv("TUTOR_ACERTOS_SUBIR", "3"))
TUTOR_ERROS_DESCER = int(os.getenv("TUTOR_ERROS_DESCER", "2"))
TUTOR_ACERTOS_CONCLUIR = int(os.getenv("TUTOR_ACERTOS_CONCLUIR", "3"))
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

# --- Segurança: autenticação e papéis (EAP 1.4.6) ---
# "desligada" = MODO DE DESENVOLVIMENTO: nenhuma rota pede login (testes e demos
# antigos), com aviso visível nas telas. Padrão: ligada. Nunca desligar com dados reais
# (com TIA_AMBIENTE=producao, o padrão, a API nem sobe desligada).
TIA_AUTH = os.getenv("TIA_AUTH", "ligada").strip().lower()
AUTH_DESLIGADA = TIA_AUTH in ("desligada", "desligado", "0", "off", "nao", "não")
# Provedor de autenticação (seguranca.autenticador): "local" (senha com scrypt).
# O login único do EBAULA (1.4.3) entra como outro provedor.
AUTH_PROVEDOR = os.getenv("AUTH_PROVEDOR", "local")
# Expiração da sessão no servidor (minutos): por inatividade (sem nenhum pedido)
# e limite absoluto, contado do login, mesmo com uso contínuo
AUTH_SESSAO_INATIVIDADE_MINUTOS = int(os.getenv("AUTH_SESSAO_INATIVIDADE_MINUTOS", "30"))
AUTH_SESSAO_MAXIMA_MINUTOS = int(os.getenv("AUTH_SESSAO_MAXIMA_MINUTOS", "480"))
# Cookie só por HTTPS (Secure). Os navegadores aceitam Secure em http://localhost;
# desligar (0) só para testar por HTTP em outra máquina.
AUTH_COOKIE_SEGURO = os.getenv("AUTH_COOKIE_SEGURO", "1").lower() in ("1", "true", "sim")
# Limite de falhas de login dentro da janela, por usuário e por IP; com o limite
# atingido, o login fica bloqueado até a janela passar (mesmo com a senha certa)
AUTH_MAX_FALHAS_USUARIO = int(os.getenv("AUTH_MAX_FALHAS_USUARIO", "5"))
AUTH_MAX_FALHAS_IP = int(os.getenv("AUTH_MAX_FALHAS_IP", "20"))
AUTH_JANELA_MINUTOS = int(os.getenv("AUTH_JANELA_MINUTOS", "15"))
# Atraso (s) na resposta de cada login que falha (atrapalha a tentativa em massa)
AUTH_ATRASO_SEGUNDOS = float(os.getenv("AUTH_ATRASO_SEGUNDOS", "1.0"))
# Política de senha: tamanho mínimo e bloqueio das senhas mais comuns (lista em
# seguranca/senhas_comuns.txt, mais o arquivo opcional AUTH_SENHAS_COMUNS_EXTRA,
# uma por linha). PROVISÓRIO até a política da instituição (Tiago).
AUTH_SENHA_MINIMA = int(os.getenv("AUTH_SENHA_MINIMA", "10"))
AUTH_SENHA_BLOQUEAR_COMUNS = os.getenv("AUTH_SENHA_BLOQUEAR_COMUNS", "1").lower() in ("1", "true", "sim")
AUTH_SENHAS_COMUNS_EXTRA = os.getenv("AUTH_SENHAS_COMUNS_EXTRA", "")
# Retenção (dias) das tentativas de login e dos pedidos sem login, que guardam o
# IP (só para os limites; o IP nunca vai para a auditoria). PROVISÓRIO (C1).
AUTH_RETENCAO_IP_DIAS = int(os.getenv("AUTH_RETENCAO_IP_DIAS", "30"))
# Limpeza periódica feita pela própria API (sessões vencidas, tentativas e
# pedidos sem login fora da retenção), a cada tantos minutos; 0 = só pelo comando
# python -m tia.seguranca.limpeza
AUTH_LIMPEZA_MINUTOS = int(os.getenv("AUTH_LIMPEZA_MINUTOS", "60"))
# Pedidos sem login (401): por origem (IP) e janela de tempo, só o primeiro vai
# para a auditoria; os demais são contados e resumidos numa linha por janela.
# No máximo AUTH_ANONIMOS_MAX_ORIGENS origens registradas uma a uma por janela.
AUTH_ANONIMOS_JANELA_MINUTOS = int(os.getenv("AUTH_ANONIMOS_JANELA_MINUTOS", "10"))
AUTH_ANONIMOS_MAX_ORIGENS = int(os.getenv("AUTH_ANONIMOS_MAX_ORIGENS", "50"))

# --- LGPD: retenção (EAP 1.4.6, C1). PROVISÓRIO: validar com o jurídico/DEP ---
# Prazos em dias, contados da data de cada registro; aplicados por
# python -m tia.seguranca.retencao --aplicar (docs/seguranca/lgpd.md).
# Respostas do questionário, sessões, decisões e reforços: desvinculados do aluno
RETENCAO_RESPOSTAS_DIAS = int(os.getenv("RETENCAO_RESPOSTAS_DIAS", "365"))
# Diálogo livre: pergunta, resposta e correção apagadas e linha desvinculada do aluno
RETENCAO_DIALOGO_DIAS = int(os.getenv("RETENCAO_DIALOGO_DIAS", "180"))
# Textos do feedback das questões (e o resultado guardado dos eventos, que os repete)
RETENCAO_FEEDBACK_TEXTO_DIAS = int(os.getenv("RETENCAO_FEEDBACK_TEXTO_DIAS", "180"))
# Auditoria: nunca é apagada; passado o prazo, só os dados pessoais dela são anonimizados
RETENCAO_AUDITORIA_DIAS = int(os.getenv("RETENCAO_AUDITORIA_DIAS", "730"))
# Cópias do banco feitas antes da retenção e da eliminação a pedido do titular
# (guardam os dados apagados: também têm prazo). COPIAS_DIR vazio = pasta
# "copias" ao lado do banco.
RETENCAO_COPIAS_DIAS = int(os.getenv("RETENCAO_COPIAS_DIAS", "30"))
COPIAS_DIR = os.getenv("COPIAS_DIR", "")

# --- Implantação na VM (EAP 1.4.1; deploy/) ---
# Backup (deploy/backup.sh): pasta e quantos dias guardar; vazio = "backup" ao lado do banco
BACKUP_DIR = os.getenv("BACKUP_DIR", "")
BACKUP_DIAS = int(os.getenv("BACKUP_DIAS", "14"))
# Endereço da API para o teste de fumaça (deploy/verificar.sh): o uvicorn, sem o proxy
API_URL_LOCAL = os.getenv("API_URL_LOCAL", "http://127.0.0.1:8000")
# Limite do R09 (s) usado no resumo de verificar.sh --medir-r09
R09_LIMITE_SEGUNDOS = float(os.getenv("R09_LIMITE_SEGUNDOS", "15"))

# --- Ambiente e API (EAP 1.4.6, D1) ---
# "producao" (padrão) ou "desenvolvimento". Em produção a API não sobe com
# configuração insegura (ver problemas_de_configuracao) e /docs fica desligado.
TIA_AMBIENTE = os.getenv("TIA_AMBIENTE", "producao").strip().lower()
EM_PRODUCAO = TIA_AMBIENTE != "desenvolvimento"
# Documentação interativa /docs, /redoc e /openapi.json (padrão: só em desenvolvimento)
API_DOCS = os.getenv("API_DOCS", "0" if EM_PRODUCAO else "1").lower() in ("1", "true", "sim")

# --- Painel do docente (EAP 1.4.5) ---
# Alerta de desempenho baixo: taxa de acerto geral abaixo deste valor, desde que o
# aluno tenha pelo menos PAINEL_MIN_RESPOSTAS respostas. PROVISÓRIO (Pessoa 4).
PAINEL_DESEMPENHO_BAIXO = float(os.getenv("PAINEL_DESEMPENHO_BAIXO", "0.5"))
PAINEL_MIN_RESPOSTAS = int(os.getenv("PAINEL_MIN_RESPOSTAS", "5"))


def problemas_de_configuracao() -> list[str]:
    """Configurações inseguras para produção (a API recusa subir com elas
    quando TIA_AMBIENTE=producao; tia.api.main)."""
    from ipaddress import ip_address
    from urllib.parse import urlparse

    problemas = []
    if AUTH_DESLIGADA:
        problemas.append("TIA_AUTH=desligada (modo de desenvolvimento) com TIA_AMBIENTE=producao")
    if not AUTH_COOKIE_SEGURO:
        problemas.append("AUTH_COOKIE_SEGURO=0: o cookie de sessão iria sem Secure")
    host = urlparse(OLLAMA_URL).hostname or ""
    try:
        local = host == "localhost" or ip_address(host).is_loopback or ip_address(host).is_private
    except ValueError:
        local = False
    if not local:
        problemas.append(f"OLLAMA_URL aponta para fora da máquina ou da rede interna ({host!r}); R07 exige LLM local")
    return problemas


def avisos_de_configuracao() -> list[str]:
    """Inconsistências que não impedem a API de subir (verificar.sh as mostra)."""
    avisos = []
    from urllib.parse import urlparse

    if (urlparse(API_URL_LOCAL).hostname or "") not in ("127.0.0.1", "localhost", "::1"):
        avisos.append(f"API_URL_LOCAL ({API_URL_LOCAL}) não é a própria máquina: o teste de fumaça iria pela rede")
    if MODELO_PADRAO not in MODELOS_LLM:
        avisos.append(f"MODELO_PADRAO ({MODELO_PADRAO}) não está em MODELOS_LLM: não é baixado nem medido")
    return avisos


if __name__ == "__main__":
    for nome in ("OLLAMA_URL", "MODELOS_LLM", "MODELO_PADRAO", "EMBED_MODEL", "RACIOCINIO_POR_MODELO",
                 "RACIOCINIO_TAGS", "BACKUP_DIR", "BACKUP_DIAS", "API_URL_LOCAL", "R09_LIMITE_SEGUNDOS",
                 "OLLAMA_KEEP_ALIVE", "DB_PATH",
                 "MATERIAIS_DIR", "CHROMA_DIR", "COLLECTION_NAME",
                 "CHUNK_SIZE", "CHUNK_OVERLAP", "EMENTA_PATH", "PERFIS_PATH", "ONBOARDING_USA_LLM",
                 "ONBOARDING_TIMEOUT_LLM", "PILOTO_PRAZO_DIAS", "PILOTO_ESCOPO", "TUTOR_ACERTOS_SUBIR",
                 "TUTOR_ERROS_DESCER", "TUTOR_ACERTOS_CONCLUIR",
                 "PLANEJADOR_TIMEOUT_LLM", "BANCO_ITENS_PATH", "TUTOR_TIMEOUT_LLM", "TUTOR_MAX_TOKENS", "TUTOR_TEMPERATURA", "TUTOR_TOP_P", "TUTOR_SEED", "TUTOR_MODO_FEEDBACK",
                 "TUTOR_NUM_TRECHOS",
                 "TUTOR_DISTANCIA_MAXIMA", "TUTOR_COBERTURA_MIN", "TUTOR_EXIGE_TERMO_RARO",
                 "INATIVIDADE_DIAS", "RELATORIO_MIN_GRUPO", "RELATORIO_TIMEOUT_LLM", "RELATORIO_MAX_TOKENS",
                 "RELATORIO_TEMPERATURA", "RELATORIO_SEED", "RELATORIO_TENDENCIA_JANELA",
                 "RELATORIO_TENDENCIA_MIN_RESPOSTAS", "RELATORIO_TENDENCIA_LIMIAR",
                 "ORQ_QUEDA_RESPOSTAS_ENTRE_REPLANOS", "ORQ_INATIVIDADE_REFAZER_DIAS",
                 "PAINEL_DESEMPENHO_BAIXO", "PAINEL_MIN_RESPOSTAS", "TIA_AUTH", "AUTH_PROVEDOR",
                 "AUTH_SESSAO_INATIVIDADE_MINUTOS", "AUTH_SESSAO_MAXIMA_MINUTOS", "AUTH_COOKIE_SEGURO",
                 "AUTH_MAX_FALHAS_USUARIO", "AUTH_MAX_FALHAS_IP", "AUTH_JANELA_MINUTOS", "AUTH_ATRASO_SEGUNDOS",
                 "AUTH_SENHA_MINIMA", "AUTH_SENHA_BLOQUEAR_COMUNS", "AUTH_SENHAS_COMUNS_EXTRA",
                 "AUTH_RETENCAO_IP_DIAS", "AUTH_LIMPEZA_MINUTOS", "AUTH_ANONIMOS_JANELA_MINUTOS",
                 "AUTH_ANONIMOS_MAX_ORIGENS", "RETENCAO_RESPOSTAS_DIAS", "RETENCAO_DIALOGO_DIAS",
                 "RETENCAO_FEEDBACK_TEXTO_DIAS", "RETENCAO_AUDITORIA_DIAS", "RETENCAO_COPIAS_DIAS", "COPIAS_DIR",
                 "TIA_AMBIENTE", "API_DOCS"):
        print(f"{nome} = {globals()[nome]}")
    for problema in problemas_de_configuracao():
        print(f"ATENÇÃO: {problema}")
    for aviso in avisos_de_configuracao():
        print(f"Aviso: {aviso}")
