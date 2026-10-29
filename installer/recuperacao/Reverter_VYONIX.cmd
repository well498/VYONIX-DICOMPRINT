@echo off
rem VYONIX - Reverter a recuperacao (pasta do programa, registro e servicos voltam; banco e dados nao sao alterados).
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Reverter_VYONIX.ps1"
echo.
pause
