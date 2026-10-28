@echo off
chcp 65001 >nul
rem VYONIX - diagnostico da instalacao no assistente do DEPLOY (somente leitura). Pede administrador.
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
cd /d "%~dp0"
echo.
echo  Diagnostico do VYONIX. O navegador deve abrir sozinho.
echo  Se nao abrir, copie o endereco "http://127.0.0.1:..." mostrado abaixo e cole no navegador.
echo.
vyonix-deploy.exe wizard --diagnose
