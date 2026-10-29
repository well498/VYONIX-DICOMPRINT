@echo off
chcp 65001 >nul
rem VYONIX - conclui a atualizacao sobre a instalacao existente: backup do banco, migracao e reinicio dos servicos.
rem Dados (ProgramData\VYONIX) preservados. Pede administrador.
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
cd /d "%~dp0"
if not exist "%ProgramData%\VYONIX\Logs" mkdir "%ProgramData%\VYONIX\Logs"
echo.
echo  VYONIX - concluindo a atualizacao (backup, migracao e servicos). Aguarde; pode levar alguns minutos.
echo  Registro: %ProgramData%\VYONIX\Logs\atualizacao.log
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\vyonix-deploy.exe' update --approve-all 2>&1 | Tee-Object -FilePath (Join-Path $env:ProgramData 'VYONIX\Logs\atualizacao.log') -Append; exit $LASTEXITCODE"
if errorlevel 1 (
  echo.
  echo  A atualizacao NAO foi concluida. Nada foi apagado; os dados estao preservados.
  echo  Use Menu Iniciar ^> VYONIX ^> "VYONIX - Reparar instalacao" ou envie o arquivo acima.
  echo.
  pause
  exit /b 1
)
echo.
echo  Atualizacao concluida. Verificando o funcionamento...
vyonix-deploy.exe verificar --esperar 180
echo.
pause
