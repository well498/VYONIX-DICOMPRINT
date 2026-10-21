"""Cabeçalho e rodapé BMP universais (``header.bmp`` e ``footer.bmp``, 3000 × 206 px, RGB 24 bits).

* Um único modelo de cabeçalho e um de rodapé, compartilhados por A4/A3, retrato/paisagem e todas as
  modalidades. No papel, a arte é redimensionada proporcionalmente para a largura útil e centralizada
  (a altura física varia com a largura disponível).
* Os modelos originais (totalmente brancos) acompanham o programa em ``print_templates/``. Os modelos em
  uso ficam em ``<ProgramData>\\VYONIX\\DICOM Print\\print_templates`` — preservados em atualizações.
* Arte personalizada em outro tamanho é **convertida** para 3000 × 206 preservando a proporção, com o
  restante preenchido de branco — nunca deformada nem cortada.
* Arquivo ausente ou corrompido na impressão: aviso registrado e a página sai sem o elemento.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import ValidationError
from app.utils.logging_setup import get_logger

log = get_logger("printing.templates")

WIDTH, HEIGHT = 3000, 206
KINDS = {"header": "header.bmp", "footer": "footer.bmp"}
LABELS = {"header": "Cabeçalho", "footer": "Rodapé"}


def bundled_dir() -> Path:
    """Pasta com os modelos originais distribuídos com o programa."""
    from app.utils.resources import resource_root
    return resource_root() / "print_templates"


def blank() -> "Image.Image":  # noqa: F821
    from PIL import Image
    return Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))


def save_bmp(img, path: Path) -> None:
    """Grava BMP RGB 24 bits de forma atômica."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    img.convert("RGB").save(tmp, "BMP")
    os.replace(tmp, path)


@dataclass(frozen=True)
class BmpInfo:
    width: int
    height: int
    mode: str
    format: str

    @property
    def is_standard(self) -> bool:
        return (self.width, self.height) == (WIDTH, HEIGHT) and self.mode == "RGB" and self.format == "BMP"


def inspect(path: Path) -> BmpInfo:
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(path) as im:
            im.load()
            return BmpInfo(im.width, im.height, im.mode, im.format or "")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValidationError(f"Arquivo inválido ou corrompido: {exc}") from exc


def conform(path: Path):
    """Converte qualquer BMP para 3000 × 206 RGB: escala proporcional (sem cortar), centralizada, fundo branco."""
    from PIL import Image
    with Image.open(path) as im:
        if im.format != "BMP":
            raise ValidationError(f"Selecione um arquivo BMP (o arquivo é {im.format or 'desconhecido'}).")
        src = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
    flat = Image.new("RGB", src.size, (255, 255, 255))
    flat.paste(src, mask=src.split()[-1] if src.mode == "RGBA" else None)
    scale = min(WIDTH / flat.width, HEIGHT / flat.height)
    w, h = max(1, round(flat.width * scale)), max(1, round(flat.height * scale))
    art = flat.resize((w, h), Image.Resampling.LANCZOS) if (w, h) != flat.size else flat
    out = blank()
    out.paste(art, ((WIDTH - w) // 2, (HEIGHT - h) // 2))
    return out


class TemplateStore:
    def __init__(self, machine_root: Path) -> None:
        self.dir = Path(machine_root) / "print_templates"

    def path(self, kind: str) -> Path:
        if kind not in KINDS:
            raise ValidationError("Use 'header' ou 'footer'.")
        return self.dir / KINDS[kind]

    def ensure(self) -> None:
        """Cria os modelos em uso a partir dos originais (ou brancos) se ainda não existirem."""
        for kind, name in KINDS.items():
            target = self.dir / name
            if target.exists():
                continue
            src = bundled_dir() / name
            try:
                if src.exists() and inspect(src).is_standard:
                    self.dir.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, target)
                else:
                    save_bmp(blank(), target)
            except Exception:  # noqa: BLE001
                log.exception("Falha ao preparar o modelo %s", name)

    def info(self, kind: str) -> BmpInfo | None:
        try:
            return inspect(self.path(kind))
        except ValidationError:
            return None

    def install(self, kind: str, source: Path, *, convert: bool = False) -> BmpInfo:
        """Instala uma arte do cliente. Fora do padrão: exige ``convert=True`` (a interface pergunta)."""
        info = inspect(Path(source))
        if info.format != "BMP":
            raise ValidationError(f"Selecione um arquivo BMP (o arquivo é {info.format or 'desconhecido'}).")
        if (info.width, info.height) != (WIDTH, HEIGHT) and not convert:
            raise NeedsConversion(info)
        img = conform(Path(source))
        target = self.path(kind)
        if target.exists():
            shutil.copyfile(target, target.with_name(target.stem + ".anterior.bmp"))
        save_bmp(img, target)
        return inspect(target)

    def restore_original(self, kind: str) -> None:
        target = self.path(kind)
        src = bundled_dir() / KINDS[kind]
        if src.exists() and inspect(src).is_standard:
            if target.exists():
                shutil.copyfile(target, target.with_name(target.stem + ".anterior.bmp"))
            self.dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
        else:
            save_bmp(blank(), target)

    def load(self, kind: str):
        """Imagem para impressão, ou ``(None, aviso)`` se ausente/corrompida."""
        from PIL import Image
        p = self.path(kind)
        try:
            with Image.open(p) as im:
                im.load()
                img = im.convert("RGB")
        except FileNotFoundError:
            return None, f"{LABELS[kind]} BMP ausente ({p}); página impressa sem {LABELS[kind].lower()}"
        except Exception as exc:  # noqa: BLE001
            return None, f"{LABELS[kind]} BMP corrompido ({exc}); página impressa sem {LABELS[kind].lower()}"
        if img.size != (WIDTH, HEIGHT):
            return None, (f"{LABELS[kind]} BMP com {img.width} × {img.height} px (esperado {WIDTH} × {HEIGHT}); "
                          f"página impressa sem {LABELS[kind].lower()}")
        return img, None


class NeedsConversion(ValidationError):
    def __init__(self, info: BmpInfo) -> None:
        self.info = info
        super().__init__(f"O arquivo tem {info.width} × {info.height} px; o padrão é {WIDTH} × {HEIGHT} px. "
                         "Ele pode ser convertido preservando a proporção (sem deformar nem cortar), com o "
                         "espaço restante em branco.")
