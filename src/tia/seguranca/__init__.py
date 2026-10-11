"""
Segurança do TIA (EAP 1.4.6, etapas 1 e 2): autenticação, sessões e papéis.

    senhas.py       hash scrypt com sal (biblioteca padrão), conferência em tempo constante,
                    política de senha (tamanho mínimo, senhas_comuns.txt)
    usuarios.py     cadastro (aluno, docente, admin) e linha de comando:
                    python -m tia.seguranca.usuarios criar|desativar|redefinir-senha|listar
    sessoes.py      sessões no servidor (só o hash do token; inatividade e limite absoluto)
                    e limite de tentativas de login
    anonimos.py     pedidos sem login (401) e logins bloqueados agregados na auditoria
    limpeza.py      retenção: sessões vencidas e IPs após AUTH_RETENCAO_IP_DIAS;
                    python -m tia.seguranca.limpeza
    autenticador.py provedor trocável (contrato Autenticador; "local" hoje, EBAULA depois)
    acesso.py       dependências do FastAPI: sessão, anti-CSRF, papéis, dono dos dados;
                    toda recusa vai para a auditoria

Rotas: tia.api.rotas_auth (/auth/login, /auth/logout, /auth/senha, /auth/eu, /admin/usuarios).
TIA_AUTH=desligada (core/config.py) é o modo de desenvolvimento: nenhuma rota
pede login e as telas mostram um aviso. Padrão: ligada.

Não é executável (exceto usuarios.py e limpeza.py); documentação em
docs/arquitetura/arquitetura.md, "Segurança", e implantação em docs/seguranca/implantacao.md.

Pré-requisitos:
    - tabelas criadas: python -m tia.core.database
"""
