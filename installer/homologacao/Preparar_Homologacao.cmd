@echo off
chcp 65001 >nul
rem VYONIX - Homologacao interna: ativa PACS (com Viewer), RIS e Laudos nesta instalacao de testes.
rem Executar como administrador (o atalho do Menu Iniciar ja pede a elevacao).
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
cd /d "%~dp0"
echo.
echo  VYONIX - preparar a homologacao interna (dados ficticios, sem licenca comercial)
echo  Ativando os modulos PACS, RIS e Laudos. Cada etapa mostra o resultado.
echo.
for %%M in (pacs ris report) do (
  echo === Modulo %%M ===
  vyonix-deploy.exe activate-module %%M --approve-all
  if errorlevel 1 (
    echo.
    echo  FALHA ao ativar o modulo %%M. Abra "VYONIX Diagnostico" no Menu Iniciar e guarde o relatorio.
    pause
    exit /b 1
  )
)
echo.
echo  Pronto. Abra o atalho "VYONIX" e entre com o administrador criado no assistente.
pause
