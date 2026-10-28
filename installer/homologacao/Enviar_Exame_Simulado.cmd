@echo off
chcp 65001 >nul
rem VYONIX - Homologacao: envia um estudo SINTETICO ao PACS local, como se fosse um tomografo.
cd /d "%~dp0"
echo.
echo  Simulador de modalidade (somente dados ficticios, somente este computador).
echo  Use o MESMO numero de prontuario do paciente ficticio cadastrado no VYONIX.
echo.
set /p PID=Numero do prontuario (ex.: HML-001): 
set /p NOME=Nome do paciente ficticio (ex.: Maria Ficticia): 
set /p ACC=Numero de acesso (opcional, Enter para pular): 
if "%ACC%"=="" (
  VyonixPlatform.exe homolog-enviar --paciente-id "%PID%" --nome "%NOME%"
) else (
  VyonixPlatform.exe homolog-enviar --paciente-id "%PID%" --nome "%NOME%" --accession "%ACC%"
)
echo.
pause
