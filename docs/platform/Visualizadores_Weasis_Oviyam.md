# Abrir imagens com Weasis e Oviyam — investigação e prova de conceito

* **Data:** 29/10/2026 · código: `vyonix/pacs/external.py`, rotas `/api/v1/pacs/external/*`, componente web
  `OpenImages` (`web/src/viewer.tsx`) · testes: `tests_platform/test_external_viewers.py`, e2e `test_e2e_web.py`.
* **Situação:** os dois visualizadores vêm **desligados** (`pacs/external_viewers`). Nada foi habilitado em
  instalação alguma. O VYONIX Viewer (OHIF) continua sendo o visualizador padrão e não foi alterado.

## 1. Menu único "Abrir imagens"

Componente reutilizável em todas as telas que já mostravam o estudo (Imagens/PACS, Laudos/Telelaudo e editor,
Central de exames, Painel do técnico, Agenda/RIS, preparação, exames anteriores e histórico do paciente):

| Opção | Disponível quando | Como abre |
|---|---|---|
| VYONIX Viewer — no navegador | sempre (quem pode abrir estudos) | lançador com protocolo e comparação |
| VYONIX Viewer — comparar com anterior | há anterior autorizado do mesmo paciente | idem |
| Abrir com Weasis — visualização avançada | administrador ligou o Weasis | link `weasis://` → aplicativo local |
| Abrir com Oviyam — visualização pelo navegador | administrador ligou **e** configurou o Oviyam | nova aba no serviço Oviyam |

Opção indisponível aparece **desabilitada com o motivo**. Exige só `pacs.studies.read` (médico, técnico,
coordenação…), não o módulo administrativo do PACS. O servidor confere em cada abertura: organização (RLS),
permissão, escopo por vínculo (`pacs/viewer.access = linked`) e compartilhamentos.

**Pacientes:** o VYONIX ainda não tem portal do paciente (planejado; depende da decisão LGPD/CFM, BLK-06). O
componente está pronto para ser usado nele; o acesso do paciente às próprias imagens exige essa entrega.

## 2. Weasis

**Compatibilidade (mecanismo oficial, conferido no código do Weasis e do weasis-dicom-tools):**
* link `weasis://?$dicom:get -w "<URL do manifesto>"` (o instalador do Weasis registra o protocolo no sistema);
* manifesto XML `http://www.weasis.org/xsd/2.5`: `arcQuery(baseUrl, arcId, requireOnlySOPInstanceUID)` →
  `httpTag` → `Patient` → `Study` → `Series` → `Instance`; o Weasis baixa cada instância por **WADO-URI**
  (`requestType=WADO&studyUID&seriesUID&objectUID&contentType=application/dicom`) enviando os `httpTag` como
  cabeçalhos HTTP;
* o manifesto gerado pelo VYONIX é **validado contra o `manifest.xsd` oficial** do Weasis no teste
  (`VYONIX_WEASIS_XSD`, executado localmente em 29/10).

**Segurança implementada:**
1. Abertura só por **POST** da sessão do VYONIX (anti-CSRF): cria um **código de manifesto de uso único, 2 minutos**.
2. O link `weasis://` leva **só esse código** — nenhuma credencial permanente na URL, nenhum link público.
3. O manifesto (HTTPS) entrega uma **credencial de acesso** de curta duração (padrão 60 min, configurável 5–480),
   presa ao **estudo**, ao **usuário** e à **organização**, no cabeçalho `Authorization: Bearer` (só o SHA-256
   é guardado).
4. O WADO-URI externo recusa credencial na URL, outro estudo (403), credencial vencida/revogada/forjada (401),
   credencial com o identificador de outra organização (401), usuário desativado ou sem permissão.
5. Arquivo entregue com a verificação de integridade (SHA-256) do PACS; identificadores DICOM originais intactos.
6. Auditoria: `pacs.viewer.external` (pedido), `pacs.viewer.external.manifest` e `pacs.study.open`
   (finalidade `weasis`, uma vez por credencial). `external.revoke_user` revoga as credenciais do usuário.

**Dependências e limites:**
* Weasis instalado no computador (instaladores oficiais com Java embutido; Windows, macOS, Linux). Licença do Weasis:
  EPL 2.0 / Apache 2.0 (projeto aberto; não é distribuído pelo VYONIX).
* **Certificado:** o Weasis é Java e só aceita HTTPS confiável. Com o certificado autoassinado da instalação local,
  o certificado precisa ser confiado no computador (ou usar certificado da instituição) — **a validar na homologação**.
* O navegador pode pedir confirmação para abrir o Weasis; o administrador pode liberar `weasis://*` por política.
* O Weasis guarda imagens em cache local no computador: orientar uso só em computadores da instituição.

## 3. Oviyam

**Investigação (fontes públicas; parte não pôde ser confirmada nesta sessão — leitura das páginas bloqueada):**
* Aplicação web Java (WAR) para Tomcat, do ecossistema dcm4che; versões 2.8.x anunciadas no grupo dcm4che
  (data e suporte atual **a confirmar**). Licença do ecossistema dcm4che: MPL 1.1 / GPL 2 / LGPL 2.1 (**a confirmar**
  para o Oviyam).
* Conecta ao PACS **com o próprio AE** (C-FIND/C-MOVE ou WADO) e tem **login próprio** (usuários do Tomcat).

**Avaliação de segurança:** com essa arquitetura o Oviyam enxerga tudo o que o AE dele pode consultar — não aplica
as permissões, o vínculo do médico nem o escopo do VYONIX por usuário; a autorização ficaria só na interface. Isso
contraria os requisitos (controle no servidor, por usuário). Somam-se dependências antigas (Java/Tomcat, bibliotecas
JavaScript) sem histórico de correções verificável e um novo serviço a instalar e manter.

**Decisão técnica:** Oviyam **não homologado**; a opção existe no menu, **desligada**, com o motivo. Quando o
administrador liga e configura (só HTTPS), o VYONIX apenas abre `viewer.html?studyUID=…&serverName=…` sem enviar
credencial alguma do VYONIX. Para visualização no navegador com as permissões do VYONIX, o caminho seguro é o
**VYONIX Viewer** (OHIF, mesma origem, DICOMweb autorizado por sessão).

**Para tornar o Oviyam seguro (proposta, exige decisão):** colocá-lo atrás do VYONIX (proxy reverso) com acesso só
por credencial de estudo de uso curto, bloqueando as telas de pesquisa e fazendo o Oviyam buscar imagens no WADO do
VYONIX com essa credencial — exige validar a versão, corrigir dependências e incluir Java/Tomcat no instalador.

## 4. Testes executados (29/10)

* `test_external_viewers.py` 3/3: desligado por padrão; só POST; link sem credencial; manifesto correto e válido no
  XSD oficial; uso único; WADO com cabeçalho, outro estudo, sem cabeçalho, credencial na URL, forjada, de outra
  organização, vencida, revogada, usuário desativado; escopo por vínculo; Oviyam só HTTPS e sem credencial.
* e2e web (Chromium): menu nas Imagens, na Agenda e na preparação; indisponíveis com motivo; VYONIX Viewer em nova aba
  sem `window.opener`; Weasis ligado gera `weasis://` sem `Bearer`.
* Não executado: abertura real no aplicativo Weasis (exige o Weasis instalado num computador com interface) — roteiro
  de homologação.
