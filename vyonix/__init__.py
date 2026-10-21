"""VYONIX — plataforma unificada (CORE).

Pacotes:

* ``config``    configuração (arquivo + variáveis de ambiente) e segredos;
* ``db``        engine, sessão com isolamento por clínica (row level security), migrações Alembic;
* ``tenancy``   organizações (clínicas), unidades e instalações;
* ``auth``      usuários, papéis com escopo por unidade, permissões, sessões e MFA (TOTP);
* ``audit``     auditoria encadeada por SHA-256 (somente inserção);
* ``events``    eventos versionados com outbox/inbox e o processador (``vyonix-worker``);
* ``settings``  configurações independentes por módulo, com histórico;
* ``modules``   registro de módulos (manifestos, dependências, habilitação);
* ``clinical``  pacientes, identificadores, atendimentos, pedidos, procedimentos e exames;
* ``licensing`` direitos por módulo (licença v3), demonstrações assinadas, compatibilidade v2;
* ``api``       API HTTP (FastAPI) e interface web.

O VYONIX DICOM Print (``app/``) continua independente nesta fase (decisão D1).
"""

__version__ = "0.2.0"
