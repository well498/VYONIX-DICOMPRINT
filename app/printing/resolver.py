"""Resolução das configurações de um trabalho, com a origem de cada valor (§10).

Precedência (da menor para a maior), até a chegada do motor de regras (Fase 6):

1. padrões do sistema (Configurações → Impressão);
2. perfil associado à impressora;
3. perfil associado à modalidade;
4. perfil associado ao equipamento (ou o perfil escolhido no cadastro do equipamento);
5. valores escolhidos manualmente na ação (ex.: reimprimir com outra impressora).

O resultado é gravado no trabalho (``settings_json`` e ``settings_origin_json``) — reprocessar
um trabalho antigo usa os valores dele, não os padrões atuais (salvo "Reprocessar com as
configurações atuais").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from app.imaging.calibration import CalibrationProfile
from app.printing.layout_engine import LayoutSpec
from app.printing.profiles import PrintProfile, ProfileService

SYSTEM = "Padrão do sistema"


@dataclass
class Resolved:
    values: dict[str, Any]
    origins: dict[str, str]
    profile_id: int | None = None

    def spec(self) -> LayoutSpec:
        v = self.values
        m = float(v["margin_mm"])
        return LayoutSpec(
            paper=v["paper"], orientation=v["orientation"], layout=v["layout"],
            margins_mm=tuple(float(x) for x in v.get("margins_mm") or (m, m, m, m)),
            spacing_mm=float(v["spacing_mm"]), border=bool(v["border"]), dpi=int(v["dpi"]),
            header_text=v["header_text"], footer_text=v["footer_text"], exam_info=bool(v["exam_info"]),
            page_numbers=bool(v["page_numbers"]),
            calibration=CalibrationProfile.from_json(v.get("calibration")),
        )


def defaults(get: Callable[[str], Any]) -> dict[str, Any]:
    return {
        "printer": get("printing.default_printer") or "",
        "paper": get("printing.paper"),
        "orientation": get("printing.orientation"),
        "layout": get("printing.layout"),
        "dpi": int(get("printing.dpi")),
        "margin_mm": int(get("printing.margin_mm")),
        "margins_mm": None,
        "spacing_mm": int(get("printing.spacing_mm")),
        "copies": int(get("printing.copies")),
        "border": bool(get("printing.border")),
        "header_text": get("printing.header_text"),
        "footer_text": get("printing.footer_text"),
        "exam_info": bool(get("printing.exam_info")),
        "patient_info": bool(get("printing.patient_info")),
        "page_numbers": bool(get("printing.page_numbers")),
        "calibration": None,
    }


def _apply_profile(values: dict, origins: dict, profile: PrintProfile, label: str) -> None:
    src = f"Perfil “{profile.name}” ({label})"
    simple = {"paper": profile.paper_size, "orientation": profile.orientation, "layout": profile.layout,
              "copies": profile.copies}
    for key, val in simple.items():
        if val:
            values[key], origins[key] = val, src
    if profile.margins:
        mg = profile.margins
        values["margins_mm"] = [float(mg.get(k, values["margin_mm"])) for k in ("top", "right", "bottom", "left")]
        origins["margins_mm"] = src
        if "spacing" in mg:
            values["spacing_mm"], origins["spacing_mm"] = float(mg["spacing"]), src
    if not profile.calibration.is_identity():
        values["calibration"], origins["calibration"] = profile.calibration.to_json(), src
    for key, val in (profile.annotations or {}).items():
        if key in ("header_text", "footer_text", "exam_info", "patient_info", "page_numbers", "border", "dpi"):
            values[key], origins[key] = val, src


def resolve(get: Callable[[str], Any], profiles: ProfileService, *, device_id: int | None = None,
            device_profile_id: int | None = None, modality: str | None = None, printer: str | None = None,
            overrides: Mapping[str, Any] | None = None, override_label: str = "Escolha manual") -> Resolved:
    values = defaults(get)
    origins = {k: SYSTEM for k in values}
    if not values["printer"]:
        origins["printer"] = "Impressora padrão do Windows"
    profile_id = None
    target_printer = (overrides or {}).get("printer") or printer or values["printer"]

    chain: list[tuple[PrintProfile | None, str]] = []
    if target_printer:
        chain.append((profiles.for_scope("printer", target_printer), "impressora"))
    if modality:
        chain.append((profiles.for_scope("modality", modality.upper()), f"modalidade {modality.upper()}"))
    if device_id:
        chain.append((profiles.for_scope("device", str(device_id)), "equipamento"))
    if device_profile_id:
        try:
            chain.append((profiles.get(device_profile_id), "cadastro do equipamento"))
        except Exception:  # noqa: BLE001 - perfil removido
            pass
    for prof, label in chain:
        if prof is not None and prof.active:
            _apply_profile(values, origins, prof, label)
            profile_id = prof.id
    if printer:
        values["printer"], origins["printer"] = printer, "Pedido"
    for key, val in (overrides or {}).items():
        if key in values and val is not None:
            values[key], origins[key] = val, override_label
    return Resolved(values, origins, profile_id)
