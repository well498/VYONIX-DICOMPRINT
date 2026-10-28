@echo off
chcp 65001 >nul
rem VYONIX - abre o assistente do VYONIX DEPLOY (instalacao, reparo, diagnostico). Pede administrador.
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
cd /d "%~dp0"
echo.
echo  Assistente do VYONIX DEPLOY. O navegador deve abrir sozinho.
echo  Se nao abrir, copie o endereco "http://127.0.0.1:..." mostrado abaixo (com o ?t=...) e cole no navegador.
echo  Deixe esta janela aberta enquanto usa o assistente.
echo.
vyonix-deploy.exe wizard
