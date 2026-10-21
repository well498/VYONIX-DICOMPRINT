# installer/

* `Vyonix.iss` — instalador comercial `VYONIX_DICOM_Print_Setup_v<versão>_x64.exe` (aplicativo, serviço
  Windows, firewall). Executa `Vyonix.exe --installation install --fresh|--upgrade` e, na desinstalação,
  `--installation uninstall` (encerra a ativação local). **Não contém o License Manager.**
* `LicenseManager.iss` — instalador opcional `VYONIX_License_Manager_Setup.exe` do aplicativo
  administrativo (mesmo executável da versão portátil).
