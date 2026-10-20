"""Identidade VYONIX — fonte única de nomes, textos e cores da marca."""

from __future__ import annotations

BRAND = "VYONIX"
PRODUCT_NAME = "VYONIX DICOM Print"
SLOGAN = "Precisão em cada imagem."
EXECUTABLE = "Vyonix.exe"
INSTALLER = "Vyonix_Setup.exe"

CLINICAL_DISCLAIMER = (
    "Versão de desenvolvimento. Este software não está validado para uso clínico "
    "e não possui declaração de conformidade DICOM."
)

# Paleta oficial. A interface usa estes valores como tokens.
COLORS = {
    "blue": "#1460F2",        # azul tecnológico (primária)
    "blue_dark": "#0B3FA8",
    "navy": "#0A1A33",        # fundo da navegação
    "silver": "#C5CED9",
    "silver_light": "#EEF2F6",
    "white": "#FFFFFF",
    "green": "#13A10E",       # estados positivos
    "amber": "#C27C0E",       # alertas
    "red": "#C42B1C",         # falhas
}
