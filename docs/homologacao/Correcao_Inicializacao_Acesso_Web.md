# Correção da inicialização e do acesso web do VYONIX

Data: 29/10/2026 · Relato: homologação de 28/10/2026 (instalação em computador/VM com Windows) — "o sistema não
inicializou e não foi possível acessar pelo IP no navegador".

## 1. Causa raiz

| # | Causa | Evidência | Efeito |
|---|---|---|---|
| 1 (comprovada) | O assistente do VYONIX DEPLOY abria o navegador com `explorer.exe "http://127.0.0.1:N/?t=…"`. O Explorer não aceita endereço com `?` na linha de comando e abre a pasta **Documentos**. O assistente nunca aparecia, o plano nunca era aprovado e **nada era configurado** (banco, serviços, certificado, firewall). | Relato do proprietário ("o deploy abriu a pasta documentos"); código `vyonix_deploy/wizard/__init__.py` anterior a `344ab09`. O CI não via o problema porque instala em modo silencioso (sem assistente). | Nenhum serviço registrado; nada atende a porta 8444; o instalador terminava como se estivesse tudo certo. |
| 2 (contribuinte) | O instalador encerrava dizendo "concluído" sem os serviços configurados e não havia atalho para o assistente nem diagnóstico que explicasse o problema. | `installer/VyonixPlatform.iss` anterior (sem atalhos antes da configuração); atalho "VYONIX" era um link direto. | O usuário via só "não foi possível acessar o site". |
| 3 (contribuinte provável no acesso pelo IP) | A regra de firewall valia só para redes **Privada** e **Domínio**. O Windows classifica redes novas — e muitas máquinas virtuais — como **Pública**. | `vyonix_deploy/steps/firewall.py` (perfis `Domain, Private`). | Funciona em `localhost`, mas outros computadores não acessam. |
| 4 (contribuinte provável) | O servidor só fala HTTPS. Quem digita `http://IP:8444` recebe "conexão redefinida/página não funciona". | Instruções e prompts usam `http://`; teste com `http.client` na porta HTTPS. | Parece que o sistema não iniciou. |

Investigado e **não** era causa: o Core escuta em `0.0.0.0` (configuração `bind`); os serviços já tinham dependência
(Core e Worker dependem do PostgreSQL), início automático e reinício após falha (5 s, 15 s, 60 s, repetido).

## 2. Correções

| Correção | Onde | Commit |
|---|---|---|
| Assistente abre o navegador por atalho de Internet temporário (`.url`), sem `?` na linha do Explorer | `vyonix_deploy/wizard/__init__.py` | `344ab09` |
| **Diagnóstico de inicialização** (sem administrador, somente leitura): instalação concluída, serviços, banco, porta (ocupada por quem), API e interface por HTTPS em `localhost` e em cada IP da rede, firewall e perfil da rede, tempo desde o boot (início atrasado) — com "como resolver" em português | `vyonix_deploy/startup.py`, `vyonix-deploy verificar` | este lote |
| Atalho **VYONIX** passa a ser `vyonix-deploy abrir`: se o sistema responde, abre o navegador; se não, abre o relatório HTML do diagnóstico | `vyonix_deploy/steps/shortcuts.py` | este lote |
| Atalhos já na instalação (antes da configuração): **"VYONIX - Assistente de instalacao"** (pede administrador) e **"VYONIX - Verificar funcionamento"** | `installer/VyonixPlatform.iss`, `installer/common/` | este lote |
| Tela final do instalador avisa que falta aprovar o plano no assistente | `installer/VyonixPlatform.iss` (`[Messages]`) | este lote |
| Ao concluir no assistente, verificação real do acesso com os endereços que responderam | `vyonix_deploy/wizard` (`/api/access`) | este lote |
| Regra de firewall complementar no perfil **Público só para a sub-rede local** (Core HTTPS e, com o PACS, DICOM 4242/4243); desligável (`firewall_public_lan`) e removida na desinstalação | `vyonix_deploy/plans.py`, `steps/firewall.py`, `steps/pacs.py`, `steps/update.py` | este lote |
| `http://` na porta do VYONIX é redirecionado para `https://` (mesmo host e caminho); nenhum dado é servido sem TLS | `vyonix/api/https_server.py`, `vyonix/winservice.py` | este lote |
| Atalho "VYONIX Diagnóstico" marcado para executar como administrador (o DEPLOY exige) | `vyonix_deploy/steps/shortcuts.py` | este lote |

## 3. Testes

**Automatizados (Linux, este ambiente):** `tests_deploy/test_startup.py` (não configurado, serviço parado, logo após
o boot, banco fora do ar, porta ocupada, API sem banco, interface ausente, IP da rede sem resposta, rede Pública sem
regra, relatório HTML seguro, comando `abrir`, regra do perfil Público, atalho); `tests_platform/test_https_server.py`
(HTTPS com vários pedidos e envio de 6 MB, redirecionamento, Host malicioso, lixo e handshake inválido);
`test_e2e_web.py::test_0_http_on_https_port_redirects` (navegador real).

**Windows real (CI deploy-windows, critérios 2.10, Windows Server 2022):**
* diagnóstico de inicialização com token restrito (sem administrador): tudo OK, `localhost` e IP da rede respondendo;
* acesso pelo IP da rede por HTTPS (API e interface) e `http://` redirecionado;
* regra do perfil Público só para `LocalSubnet`;
* banco derrubado à força (processo encerrado): recuperado pelo Windows e o sistema volta a responder;
* tudo parado: iniciar o Core sobe o banco antes (dependência) e o acesso volta.
* Já cobertos antes e mantidos: instalação limpa silenciosa, primeira inicialização, reinício do serviço, processo do
  Core encerrado à força, porta ocupada (detectada e reparada), atualização preservando dados, desinstalação.

**Não executados (sem ambiente):** reinicialização real do Windows (o runner do CI não reinicia), instalação em
diretório diferente (o instalador não oferece escolha de pasta: `DisableDirPage`), Windows 10/11 de mesa (BLK-04).
O comportamento após reiniciar é coberto indiretamente: serviços com início automático e dependência; o diagnóstico
informa "aguarde" nos primeiros 5 minutos após ligar.

## 4. Como verificar o acesso depois de instalar

1. Menu Iniciar → **VYONIX → "VYONIX - Verificar funcionamento"** (ou **"VYONIX"** depois de configurado).
   Funcionando: o navegador abre o sistema. Não funcionando: abre o diagnóstico com o que falhou e como resolver.
2. No próprio computador: `https://localhost:8444` (ou `http://localhost:8444`, que redireciona).
3. Na rede local: `https://IP_DO_SERVIDOR:8444` — o diagnóstico lista os IPs que responderam.
4. Primeiro acesso: aviso de certificado (certificado da própria instalação) → Avançado → Continuar.
