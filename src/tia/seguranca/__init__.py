"""
Segurança do TIA (EAP 1.4.6, etapa 1): autenticação, sessões e papéis.

    senhas.py       hash scrypt com sal (biblioteca padrão), conferência em tempo constante
    usuarios.py     cadastro (aluno, docente, admin) e linha de comando:
                    python -m tia.seguranca.usuarios criar|desativar|redefinir-senha|listar
    sessoes.py      sessões no servidor (só o hash do token) e limite de tentativas de login
    autenticador.py provedor trocável (contrato Autenticador; "local" hoje, EBAULA depois)
    acesso.py       dependências do FastAPI: sessão, anti-CSRF, papéis, dono dos dados;
                    toda recusa vai para a auditoria

Rotas: tia.api.rotas_auth (/auth/login, /auth/logout, /auth/eu, /admin/usuarios).
TIA_AUTH=desligada (core/config.py) é o modo de desenvolvimento: nenhuma rota
pede login e as telas mostram um aviso. Padrão: ligada.

Não é executável (exceto usuarios.py); documentação em docs/arquitetura/arquitetura.md, "Segurança".

Pré-requisitos:
    - tabelas criadas: python -m tia.core.database
"""
