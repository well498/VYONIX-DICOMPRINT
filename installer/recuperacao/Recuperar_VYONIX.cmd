@echo off
rem VYONIX - Recuperacao de instalacao com defeito.
rem 1) Sempre faz o DIAGNOSTICO (nada alterado: so le) e gera um relatorio na Area de Trabalho.
rem 2) Pergunta se deve APLICAR. Ao aplicar, mostra o plano e exige digitar RECUPERAR; faz e testa um backup antes
rem    de remover algo. Dados nunca sao alterados. Para desfazer: Reverter_VYONIX.cmd.
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Recuperar_VYONIX.ps1"
echo.
choice /C SN /M "Ver o plano e aplicar a recuperacao (pede confirmacao; DADOS PRESERVADOS)"
if errorlevel 2 goto fim
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Recuperar_VYONIX.ps1" -Aplicar
:fim
echo.
pause
