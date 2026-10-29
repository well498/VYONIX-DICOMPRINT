@echo off
rem VYONIX - validacao da instalacao (somente leitura). Gera um relatorio na Area de Trabalho.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Validar_VYONIX.ps1" %*
echo.
pause
