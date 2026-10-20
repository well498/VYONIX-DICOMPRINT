"""SOP Classes e sintaxes de transferência aceitas — fonte única para o SCP e para a
declaração de conformidade DICOM.

Princípio: o Storage SCP só aceita sintaxes de transferência que o VYONIX consegue decodificar
para impressão. Quando o equipamento propõe também uma sintaxe não comprimida (o padrão
exige Implicit VR Little Endian como mínimo), a negociação a escolhe.
"""

from __future__ import annotations

VERIFICATION = "1.2.840.10008.1.1"

# Sintaxes de transferência (PS3.5 / PS3.6)
IMPLICIT_LE = "1.2.840.10008.1.2"
EXPLICIT_LE = "1.2.840.10008.1.2.1"
DEFLATED_LE = "1.2.840.10008.1.2.1.99"
EXPLICIT_BE = "1.2.840.10008.1.2.2"
RLE_LOSSLESS = "1.2.840.10008.1.2.5"
JPEG_BASELINE = "1.2.840.10008.1.2.4.50"
JPEG_EXTENDED = "1.2.840.10008.1.2.4.51"
JPEG_LOSSLESS = "1.2.840.10008.1.2.4.57"
JPEG_LOSSLESS_SV1 = "1.2.840.10008.1.2.4.70"
JPEG_LS_LOSSLESS = "1.2.840.10008.1.2.4.80"
JPEG_LS_LOSSY = "1.2.840.10008.1.2.4.81"
JPEG_2000_LOSSLESS = "1.2.840.10008.1.2.4.90"
JPEG_2000 = "1.2.840.10008.1.2.4.91"

TRANSFER_SYNTAX_NAMES = {
    IMPLICIT_LE: "Implicit VR Little Endian", EXPLICIT_LE: "Explicit VR Little Endian",
    DEFLATED_LE: "Deflated Explicit VR Little Endian", EXPLICIT_BE: "Explicit VR Big Endian",
    RLE_LOSSLESS: "RLE Lossless", JPEG_BASELINE: "JPEG Baseline (Process 1)",
    JPEG_EXTENDED: "JPEG Extended (Process 2 & 4)", JPEG_LOSSLESS: "JPEG Lossless (Process 14)",
    JPEG_LOSSLESS_SV1: "JPEG Lossless SV1 (Process 14, SV1)", JPEG_LS_LOSSLESS: "JPEG-LS Lossless",
    JPEG_LS_LOSSY: "JPEG-LS Near-Lossless", JPEG_2000_LOSSLESS: "JPEG 2000 Lossless",
    JPEG_2000: "JPEG 2000",
}

UNCOMPRESSED = [EXPLICIT_LE, IMPLICIT_LE, DEFLATED_LE, EXPLICIT_BE]


def accepted_transfer_syntaxes() -> list[str]:
    """Sintaxes aceitas = as que o pipeline de imagem consegue decodificar neste executável."""
    from app.imaging import codecs  # importação tardia: o SCP não depende do motor de imagem
    return [ts for ts in UNCOMPRESSED + codecs.decodable_compressed() if ts in TRANSFER_SYNTAX_NAMES]


# SOP Classes de imagem aceitas pelo Storage SCP (PS3.4 Annex B)
IMAGE_STORAGE: dict[str, str] = {
    "1.2.840.10008.5.1.4.1.1.1": "Computed Radiography Image Storage (CR)",
    "1.2.840.10008.5.1.4.1.1.1.1": "Digital X-Ray Image Storage - For Presentation (DX)",
    "1.2.840.10008.5.1.4.1.1.1.1.1": "Digital X-Ray Image Storage - For Processing (DX)",
    "1.2.840.10008.5.1.4.1.1.1.2": "Digital Mammography X-Ray Image Storage - For Presentation (MG)",
    "1.2.840.10008.5.1.4.1.1.1.2.1": "Digital Mammography X-Ray Image Storage - For Processing (MG)",
    "1.2.840.10008.5.1.4.1.1.2": "CT Image Storage (CT)",
    "1.2.840.10008.5.1.4.1.1.2.1": "Enhanced CT Image Storage (CT)",
    "1.2.840.10008.5.1.4.1.1.3.1": "Ultrasound Multi-frame Image Storage (US)",
    "1.2.840.10008.5.1.4.1.1.4": "MR Image Storage (MR)",
    "1.2.840.10008.5.1.4.1.1.4.1": "Enhanced MR Image Storage (MR)",
    "1.2.840.10008.5.1.4.1.1.6.1": "Ultrasound Image Storage (US)",
    "1.2.840.10008.5.1.4.1.1.7": "Secondary Capture Image Storage (OT)",
    "1.2.840.10008.5.1.4.1.1.7.1": "Multi-frame Single Bit Secondary Capture Image Storage",
    "1.2.840.10008.5.1.4.1.1.7.2": "Multi-frame Grayscale Byte Secondary Capture Image Storage",
    "1.2.840.10008.5.1.4.1.1.7.3": "Multi-frame Grayscale Word Secondary Capture Image Storage",
    "1.2.840.10008.5.1.4.1.1.7.4": "Multi-frame True Color Secondary Capture Image Storage",
    "1.2.840.10008.5.1.4.1.1.12.1": "X-Ray Angiographic Image Storage (XA)",
    "1.2.840.10008.5.1.4.1.1.12.1.1": "Enhanced XA Image Storage (XA)",
    "1.2.840.10008.5.1.4.1.1.12.2": "X-Ray Radiofluoroscopic Image Storage (RF)",
    "1.2.840.10008.5.1.4.1.1.12.2.1": "Enhanced XRF Image Storage (RF)",
    "1.2.840.10008.5.1.4.1.1.13.1.3": "Breast Tomosynthesis Image Storage (MG)",
    "1.2.840.10008.5.1.4.1.1.20": "Nuclear Medicine Image Storage (NM)",
    "1.2.840.10008.5.1.4.1.1.128": "Positron Emission Tomography Image Storage (PT)",
    "1.2.840.10008.5.1.4.1.1.130": "Enhanced PET Image Storage (PT)",
}
