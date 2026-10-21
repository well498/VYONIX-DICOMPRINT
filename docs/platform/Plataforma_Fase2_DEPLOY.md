# VYONIX DEPLOY — Fase 2 (instalador inteligente, Windows)

Estado: **em desenvolvimento**, validado no runner Windows do CI (ver seção 8). Não declarado pronto
para uso clínico nem homologado em servidor de clínica.

## 1. O que é

Toda instalação, atualização, reparo, reconfiguração, restauração ou desinstalação é uma **execução**:

1. **Inventário** (somente leitura): sistema, CPU, memória, discos, interfaces (IP, máscara, gateway,
   DNS, DHCP), portas em uso e processo dono, serviços relevantes (outro PostgreSQL, outro PACS),
   perfis e regras de firewall do VYONIX, privilégio administrativo, certificados, instalações
   anteriores (VYONIX e DICOM Print), reinicialização pendente.
2. **Compatibilidade**: atendido, alerta, informação ou impeditivo (Windows 10 1809/Server 2019+,
   64 bits, administrador, ≥ 4 GB de memória, ≥ 10 GB livres, portas livres). Com impeditivo, nada é
   alterado e o relatório é gerado mesmo assim.
3. **Plano**: cada item com estado atual, proposto, impacto, reinicialização e como desfazer. Itens
   já conformes aparecem como tal e não são reaplicados.
4. **Aprovação**: plano inteiro ou item por item; mudanças críticas exigem o texto de confirmação
   (IP fixo: `ALTERAR IP`; restauração: `RESTAURAR <backup>`). Registrada com usuário do Windows,
   data e SHA-256 do plano. Um plano aprovado em arquivo só vale se o plano gerado agora for igual.
5. **Aplicação**: cada passo `check` → `capture` (estado anterior) → `apply` → `verify` no estado
   real. Falha ou não confirmação → reversão, em ordem inversa, dos passos reversíveis desta execução.
6. **Retomada**: o estado de cada passo é gravado (SQLite com `synchronous=FULL`) antes e depois;
   uma execução interrompida (queda de energia, processo encerrado) é retomada do último passo
   confirmado na próxima chamada.
7. **Relatório PDF e manifesto JSON** em toda execução (seção 5).

## 2. Componentes

| Componente | Função |
|---|---|
| `VYONIX_Setup_x64.exe` (Inno Setup) | Copia o programa (Python embutido via PyInstaller + PostgreSQL 17.11 oficial) e abre o assistente. Não configura nada sozinho, exceto no modo silencioso explícito. Para os serviços do VYONIX antes de copiar uma nova versão. |
| Assistente (`vyonix-deploy wizard`) | Página local em `127.0.0.1`, porta aleatória, link com token de uso único trocado por cookie `HttpOnly`/`SameSite=Strict`; requisições exigem cabeçalho próprio; encerra após 2 h sem uso. |
| `vyonix-deploy` (CLI) | `inventory`, `install|update|repair|reconfigure|restore|uninstall` com `--plan-only`, `--approve plano.json`, `--approve-all`, `--confirm`, `--silent`; `diagnose`, `resume`, `backups`, `verify-reports`, `activate-module`. |
| Banco do DEPLOY | `ProgramData\VYONIX\Deploy\deploy.db` (execuções, passos, estados anteriores, aprovações, eventos, relatórios). Independente do PostgreSQL. |
| `VyonixPlatform.exe` | Core (`serve`), Worker (`worker`) e hospedeiro dos serviços Windows (`service core|worker`). |

## 3. O que a instalação configura

| Item | Configuração |
|---|---|
| Pastas | `Program Files\VYONIX\Platform` (programa); `ProgramData\VYONIX\{Platform, PostgreSQL\17\data, Backups, Deploy\relatorios}`; cofre `Licensing` compartilhado com o DICOM Print. |
| Permissões | Sem herança; somente SYSTEM, Administradores e a conta de serviço que precisa (PostgreSQL, Core, Worker). No cofre de licenciamento, só **acrescenta** as contas do Core/Worker (as permissões do DICOM Print não mudam). |
| PostgreSQL | Instância própria (`VyonixPostgreSQL`), só `127.0.0.1`, porta do plano (padrão 5544), `scram-sha-256`, checksums de página, superusuário com senha aleatória protegida por DPAPI de máquina. Outro PostgreSQL existente não é tocado. |
| Banco do Core | Papéis `vyonix_owner`/`vyonix_app`/`vyonix_service` (privilégio mínimo, RLS), migrações, organização e primeiro administrador. |
| Serviços | `VyonixPostgreSQL`, `VyonixCore`, `VyonixWorker`: conta virtual `NT SERVICE\<nome>` (sem senha), início automático (atrasado para Core/Worker), dependência do banco, reinício automático após falha (5 s, 15 s, 60 s). |
| HTTPS | Certificado da instituição (.pfx, cadeia validada pelo Windows) ou autoassinado (ECDSA P-256), registrado como pendência de segurança. |
| Firewall | Regra `VYONIX - Core HTTPS - <porta>` (nome interno `VYONIX-core-https-<porta>`), entrada TCP, só o programa do VYONIX, perfis privado e de domínio, origens opcionais. O firewall nunca é ligado/desligado; regras alheias nunca são alteradas. |
| Atalhos | Menu Iniciar › VYONIX: VYONIX, VYONIX Administração, VYONIX Diagnóstico, VYONIX Relatórios Técnicos. |
| Rede | Padrão: **manter o IP**. IP fixo só com confirmação, após verificar conflito (ARP/ping); tarefa de segurança agendada restaura em 3 min se o DEPLOY for interrompido; sem gateway/DNS em 60 s, desfaz na hora. |

## 4. Atualização, restauração e desinstalação

- **Atualizar**: o instalador para os serviços e copia a nova versão; o DEPLOY faz **backup**
  (`pg_dump` + configuração, SHA-256 conferido e lido por `pg_restore --list`) antes das migrações e
  religa os serviços. Dados e configurações são preservados.
- **Restaurar backup** (destrutivo): exige a confirmação `RESTAURAR <backup>`; faz antes um backup do
  estado atual; restauração em transação única.
- **Desinstalar**: remove serviços, regra de firewall e atalhos. Dados, relatórios, cluster do banco e
  o DICOM Print são preservados.
- **Ativar módulo**: direito assinado → dependências → preparo do que falta → teste → habilitação →
  relatório complementar, sem reinstalar.

## 5. Relatório e manifesto

`VYONIX_Relatorio_Implantacao_<InstallationID>_<AAAAMMDD-HHMMSS>.pdf` e
`VYONIX_Manifesto_<InstallationID>_<AAAAMMDD-HHMMSS>.json` em `Deploy\relatorios` (nunca sobrescritos):
identificação, inventário, compatibilidade, rede, cada alteração (antes, final verificado,
resultado, reinicialização, como conferir), firewall, serviços, HTTPS, DICOM, testes (Aprovado,
Reprovado, Não executado, Não aplicável, Pendente de intervenção manual) e intervenções futuras.
Manifesto `vyonix-deploy-manifest/1` com SHA-256 do PDF e do manifesto anterior (cadeia); o SHA-256 de
cada arquivo fica no banco do DEPLOY (`vyonix-deploy verify-reports` aponta alteração ou remoção).
Redação antes da geração (senhas, URLs com senha, chaves privadas, tokens, blobs DPAPI e os valores
reais dos segredos locais); se algo escapar, o relatório é recusado.

## 6. Diagnóstico e reparo

`vyonix-deploy diagnose` (somente leitura): serviços parados ou alterados, regras de firewall
ausentes ou alteradas, porta ocupada por outro processo, certificado vencido ou a ≤ 60 dias,
permissões e pastas, banco (conexão, falhas de checksum), relatórios alterados e diferenças em relação
ao último manifesto. `vyonix-deploy repair` transforma o diagnóstico em plano (porta ocupada → mover o
HTTPS para porta livre, com firewall, configuração e atalhos), espera a aprovação e gera novo PDF.

## 7. Uso

```
VYONIX_Setup_x64.exe                                   (assistente)
vyonix-deploy install --config opcoes.json --plan-only --out plano.json
vyonix-deploy install --config opcoes.json --approve plano.json --silent
VYONIX_Setup_x64.exe /VERYSILENT /DEPLOYCONFIG=C:\opcoes.json   (com VYONIX_ADMIN_PASSWORD)
VYONIX_Setup_x64.exe /VERYSILENT /DEPLOYUPDATE=1
```

`opcoes.json`: `organization`, `organization_name`, `admin_user`, `https_port`, `pg_port`,
`firewall_sources`, `tls_pfx`, `network` (`mode` keep|static, `interface`, `ip`, `prefix`, `gateway`,
`dns`, `confirmed`), `shortcuts`. Senhas só por variável de ambiente ou digitadas.

## 8. Validação

Pipeline `deploy-windows.yml` (windows-2022): testes do motor; empacotamento; e aceitação real
(`tools/ci_deploy_acceptance.py`) com o resultado de cada critério da seção 13 do plano. Resultados
da última execução: ver a seção "Estado da implantação" do documento de arquitetura.

Não testado automaticamente (roteiro manual): mudança de IP na interface principal de um servidor
real, certificados de autoridade pública e Linux. Impressão de teste no DICOM Print durante a
coexistência: coberta pelos testes do próprio DICOM Print, não por este pipeline.
