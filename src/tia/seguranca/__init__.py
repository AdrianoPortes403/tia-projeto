"""
Segurança e LGPD do TIA (EAP 1.4.6): autenticação, sessões, papéis, retenção e direitos do titular.

    senhas.py       hash scrypt com sal (biblioteca padrão), conferência em tempo constante,
                    política de senha (tamanho mínimo, senhas_comuns.txt)
    usuarios.py     cadastro (aluno, docente, admin) e linha de comando:
                    python -m tia.seguranca.usuarios criar|desativar|redefinir-senha|listar|importar
    sessoes.py      sessões no servidor (só o hash do token; inatividade e limite absoluto)
                    e limite de tentativas de login
    anonimos.py     pedidos sem login (401) e logins bloqueados agregados na auditoria
    limpeza.py      retenção: sessões vencidas e IPs após AUTH_RETENCAO_IP_DIAS;
                    python -m tia.seguranca.limpeza
    anonimizacao.py o que é anonimizar (desvincular e apagar textos) e cópia do banco
    retencao.py     prazos de retenção (LGPD): python -m tia.seguranca.retencao --simular|--aplicar
    titular.py      direitos do titular: python -m tia.seguranca.titular exportar|eliminar --aluno ID
    autenticador.py provedor trocável (contrato Autenticador; "local" hoje, EBAULA depois)
    acesso.py       dependências do FastAPI: sessão, anti-CSRF, papéis, dono dos dados;
                    toda recusa vai para a auditoria

Rotas: tia.api.rotas_auth (/auth/login, /auth/logout, /auth/senha, /auth/eu, /admin/usuarios).
TIA_AUTH=desligada (core/config.py) é o modo de desenvolvimento: nenhuma rota
pede login e as telas mostram um aviso. Padrão: ligada.

Não é executável (exceto usuarios.py, limpeza.py, retencao.py e titular.py); documentação
em docs/arquitetura/arquitetura.md, "Segurança", LGPD em docs/seguranca/lgpd.md e
implantação em docs/seguranca/implantacao.md.

Pré-requisitos:
    - tabelas criadas: python -m tia.core.database
"""
