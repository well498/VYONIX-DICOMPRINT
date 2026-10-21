"""Resolução das configurações de um trabalho, com a origem de cada valor.

Hierarquia (da menor para a maior prioridade):

1. configurações globais do VYONIX (Configurações → Impressão / Identidade da Impressão);
2. perfil da impressora e **perfil padrão da modalidade**;
3. pedido **DICOM Print** — quando a política do equipamento é "equipamento prevalece";
4. perfil escolhido no cadastro do equipamento (compatibilidade);
5. **configurações gerais do equipamento** (``device_settings``, exclusivas dele);
6. **regras** — gerais e, acima delas, as regras do próprio equipamento (inclui o perfil de
   calibração que a regra indicar);
7. pedido **DICOM Print** — quando a política é "pedido DICOM prevalece";
8. escolha manual na ação (ex.: reimprimir com outra impressora).

A política do pedido DICOM Print (``dicom_policy``) vem da regra, das configurações do equipamento
ou do padrão global, nessa ordem; "ignorar" descarta os parâmetros do pedido. O resultado e a
origem de cada valor ficam gravados no trabalho; uma configuração de equipamento nunca afeta outro.
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
        custom = None
        if v["paper"] == "custom":
            from app.printing.paper import parse_custom
            custom = parse_custom(v.get("paper_custom") or "210x330")
        return LayoutSpec(
            paper=v["paper"], orientation=v["orientation"], layout=v["layout"], custom_mm=custom,
            margins_mm=tuple(float(x) for x in v.get("margins_mm") or (m, m, m, m)),
            spacing_mm=float(v["spacing_mm"]), border=bool(v["border"]), dpi=int(v["dpi"]),
            header_text=v["header_text"], footer_text=v["footer_text"], exam_info=bool(v["exam_info"]),
            page_numbers=bool(v["page_numbers"]), background=int(v.get("background", 255)),
            calibration=CalibrationProfile.from_json(v.get("calibration")),
            header_image=bool(v.get("header_enabled")), footer_image=bool(v.get("footer_enabled")),
            header_gap_mm=float(v.get("header_gap_mm") or 0), footer_gap_mm=float(v.get("footer_gap_mm") or 0),
            extra_margin_mm=float(v.get("extra_margin_mm") or 0),
        )

    def tone(self):
        from app.imaging.tone import ToneControls
        return ToneControls.from_values(self.values)


def defaults(get: Callable[[str], Any]) -> dict[str, Any]:
    return {
        "printer": get("printing.default_printer") or "",
        "paper": get("printing.paper"),
        "paper_custom": get("printing.custom_paper"),
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
        "calibration_profile_id": None,
        "background": 255,
        "keep_positions": False,
        "brightness": 0.0,
        "contrast": 0.0,
        "gamma": 0.0,
        "invert": False,
        "header_enabled": bool(get("print_identity.header_enabled")),
        "footer_enabled": bool(get("print_identity.footer_enabled")),
        "header_gap_mm": float(get("print_identity.gap_mm")),
        "footer_gap_mm": float(get("print_identity.gap_mm")),
        "extra_margin_mm": 0.0,
        "auto_print": bool(get("jobs.auto_print")),
        "dicom_policy": get("dicom.print.policy"),
        "sheet": None,
    }


def _set(values: dict, origins: dict, key: str, val: Any, origin: str) -> None:
    if key not in values or val is None:
        return
    values[key], origins[key] = val, origin
    if key == "margin_mm":                      # margem única substitui margens individuais anteriores
        values["margins_mm"], origins["margins_mm"] = None, origin


def _apply_calibration_profile(values, origins, profiles, pid, origin) -> None:
    try:
        prof = profiles.get(int(pid))
    except Exception:  # noqa: BLE001 - perfil removido
        return
    if prof.active:
        values["calibration"], origins["calibration"] = prof.calibration.to_json(), f"{origin} (perfil “{prof.name}”)"
        values["calibration_profile_id"], origins["calibration_profile_id"] = prof.id, origin


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
            overrides: Mapping[str, Any] | None = None, override_label: str = "Escolha manual",
            rules=None, device_printer: str | None = None, device_settings: Mapping[str, Any] | None = None,
            dicom: Mapping[str, Any] | None = None, device_name: str | None = None) -> Resolved:
    """``rules``: ``app.rules.engine.Evaluation`` (ou None); ``dicom``: parâmetros do pedido DICOM Print;
    ``overrides``: escolha manual; ``device_settings``: configurações gerais do equipamento."""
    values = defaults(get)
    origins = {k: SYSTEM for k in values}
    if not values["printer"]:
        origins["printer"] = "Impressora padrão do Windows"
    profile_id = None
    dev = dict(device_settings or {})
    rule_vals = dict(rules.values) if rules is not None else {}
    dev_label = f"Equipamento “{device_name}”" if device_name else "Equipamento"

    # Política do pedido DICOM Print: regra > equipamento > global
    if "dicom_policy" in rule_vals:
        policy, policy_origin = rule_vals["dicom_policy"], rules.origins["dicom_policy"]
    elif dev.get("dicom_policy"):
        policy, policy_origin = dev["dicom_policy"], dev_label
    else:
        policy, policy_origin = values["dicom_policy"], SYSTEM
    values["dicom_policy"], origins["dicom_policy"] = policy, policy_origin
    dicom = dict(dicom or {})
    if policy == "ignore_dicom":
        dicom = {}

    target_printer = ((overrides or {}).get("printer") or printer or rule_vals.get("printer") or dev.get("printer")
                      or device_printer or values["printer"])

    # 2. perfis da impressora e da modalidade
    chain: list[tuple[PrintProfile | None, str]] = []
    if target_printer:
        chain.append((profiles.for_scope("printer", target_printer), "impressora"))
    if modality:
        chain.append((profiles.for_scope("modality", modality.upper()), f"modalidade {modality.upper()}"))
    for prof, label in chain:
        if prof is not None and prof.active:
            _apply_profile(values, origins, prof, label)
            profile_id = prof.id

    # 3. pedido DICOM Print abaixo do equipamento
    if policy == "device_first":
        for key, val in dicom.items():
            _set(values, origins, key, val, "Pedido DICOM Print")

    # 4. perfis ligados ao equipamento (compatibilidade com versões anteriores)
    dev_chain = []
    if device_id:
        dev_chain.append((profiles.for_scope("device", str(device_id)), "equipamento"))
    if device_profile_id:
        try:
            dev_chain.append((profiles.get(device_profile_id), "cadastro do equipamento"))
        except Exception:  # noqa: BLE001 - perfil removido
            pass
    for prof, label in dev_chain:
        if prof is not None and prof.active:
            _apply_profile(values, origins, prof, label)
            profile_id = prof.id
    if device_printer:
        values["printer"], origins["printer"] = device_printer, "Cadastro do equipamento"

    # 5. configurações gerais do equipamento
    for key, val in dev.items():
        if key == "calibration_profile_id":
            _apply_calibration_profile(values, origins, profiles, val, dev_label)
        elif key != "dicom_policy":
            _set(values, origins, key, val, dev_label)

    # 6. regras (a avaliação já ordena: regras do equipamento acima das gerais)
    if rules is not None and rules.profile_id:
        try:
            prof = profiles.get(rules.profile_id)
            if prof.active:
                _apply_profile(values, origins, prof, f"regra “{rules.profile_rule}”")
                profile_id = prof.id
        except Exception:  # noqa: BLE001 - perfil removido depois da regra
            pass
    for key, val in rule_vals.items():
        if key == "calibration_profile_id":
            _apply_calibration_profile(values, origins, profiles, val, rules.origins[key])
        elif key != "dicom_policy":
            _set(values, origins, key, val, rules.origins[key])

    # 7. pedido DICOM Print acima de tudo (política "pedido prevalece")
    if policy == "dicom_first":
        for key, val in dicom.items():
            _set(values, origins, key, val, "Pedido DICOM Print")
    if dicom.get("keep_positions") and values.get("layout") != dicom.get("layout"):
        # O layout do pedido não prevaleceu: as posições do filme não se aplicam ao layout escolhido.
        values["keep_positions"], origins["keep_positions"] = False, "Layout do pedido não aplicado"

    # 8. escolha manual
    if printer:
        values["printer"], origins["printer"] = printer, "Pedido"
    for key, val in (overrides or {}).items():
        if key in values and val is not None:
            _set(values, origins, key, val, override_label)
    return Resolved(values, origins, profile_id)
