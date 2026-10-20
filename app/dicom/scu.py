"""Cliente DICOM (SCU): teste de conectividade C-ECHO e envio C-STORE (autoteste e testes)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterable

from app.dicom import sop

DEFAULT_CALLING_AE = "VYONIX"


def echo(host: str, port: int, called_ae: str, *, calling_ae: str = DEFAULT_CALLING_AE,
         timeout: float = 10.0) -> dict[str, Any]:
    from pynetdicom import AE

    ae = AE(ae_title=calling_ae)
    ae.add_requested_context(sop.VERIFICATION)
    ae.acse_timeout = ae.dimse_timeout = ae.network_timeout = timeout
    ae.connection_timeout = timeout
    started = time.perf_counter()
    assoc = ae.associate(host, int(port), ae_title=called_ae)
    try:
        if assoc.is_established:
            status = assoc.send_c_echo()
            ms = round((time.perf_counter() - started) * 1000)
            code = int(status.Status) if status and "Status" in status else None
            ok = code == 0x0000
            return {"ok": ok, "status": code, "ms": ms,
                    "detail": f"sucesso em {ms} ms" if ok else
                              ("sem resposta ao C-ECHO" if code is None else f"status 0x{code:04X}")}
        if assoc.is_rejected:
            return {"ok": False, "status": None, "ms": None,
                    "detail": "associação recusada pelo equipamento (verifique o AE Title)"}
        if assoc.is_aborted:
            return {"ok": False, "status": None, "ms": None, "detail": "associação abortada"}
        return {"ok": False, "status": None, "ms": None,
                "detail": f"sem conexão com {host}:{port}"}
    finally:
        if assoc.is_established:
            assoc.release()
        ae.shutdown()


def store_files(host: str, port: int, called_ae: str, files: Iterable[Path], *,
                calling_ae: str = DEFAULT_CALLING_AE, timeout: float = 30.0) -> list[int | None]:
    """Envia arquivos DICOM por C-STORE e devolve o status de cada um (None = sem resposta)."""
    from pydicom import dcmread
    from pynetdicom import AE

    datasets = [dcmread(str(f)) for f in files]
    ae = AE(ae_title=calling_ae)
    ae.acse_timeout = ae.dimse_timeout = ae.network_timeout = timeout
    for uid in sorted({str(ds.SOPClassUID) for ds in datasets}):
        own = [str(ds.file_meta.TransferSyntaxUID) for ds in datasets if str(ds.SOPClassUID) == uid]
        ae.add_requested_context(uid, list(dict.fromkeys(own[:1] + sop.UNCOMPRESSED)))
    assoc = ae.associate(host, int(port), ae_title=called_ae)
    out: list[int | None] = []
    try:
        if not assoc.is_established:
            raise ConnectionError("associação não estabelecida")
        for ds in datasets:
            status = assoc.send_c_store(ds)
            out.append(int(status.Status) if status and "Status" in status else None)
        return out
    finally:
        if assoc.is_established:
            assoc.release()
        ae.shutdown()
