@echo off
chcp 65001 >nul
rem VYONIX - Reparar instalacao: diagnostica e mostra o plano de reparo; so aplica depois de voce digitar SIM.
rem Dados (ProgramData\VYONIX) preservados. Pede administrador.
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
cd /d "%~dp0"
if not exist "%ProgramData%\VYONIX\Logs" mkdir "%ProgramData%\VYONIX\Logs"
echo.
echo  VYONIX - Reparar instalacao
echo  1) diagnostico do banco, servicos, firewall, certificado e acesso;  2) plano de reparo;  3) aplica so com SIM.
echo.
vyonix-deploy.exe repair
set R=%ERRORLEVEL%
echo.
if "%R%"=="0" (
  echo  Verificando o funcionamento...
  vyonix-deploy.exe verificar --esperar 180
) else (
  echo  O reparo nao foi aplicado ou nao foi concluido ^(codigo %R%^). Nada foi apagado; os dados estao preservados.
  echo  Relatorios: %ProgramData%\VYONIX\Deploy\relatorios
)
echo.
pause
