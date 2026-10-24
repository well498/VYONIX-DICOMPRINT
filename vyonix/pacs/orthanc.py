"""Cliente do Orthanc pela API REST nativa (núcleo GPLv3, processo separado, sem plugins).

Endpoints usados (documentação oficial da API REST do Orthanc):
* ``GET /system`` — versão e estado;
* ``POST /instances`` — guarda um arquivo DICOM (corpo ``application/dicom``);
* ``GET /instances/{id}/file`` — arquivo original;
* ``GET /changes?since=N&limit=M`` — instâncias novas (recebidas por C-STORE);
* ``GET /instances/{id}/metadata?expand`` — origem (CalledAET, RemoteAET, RemoteIP; Orthanc ≥ 1.4);
* ``DELETE /instances/{id}``.
"""

from __future__ import annotations

import httpx

from vyonix.pacs.backend import BackendUnavailable, Change, StoredRef


class OrthancBackend:
    name = "orthanc"

    def __init__(self, url: str, *, username: str | None = None, password: str | None = None,
                 timeout: float = 30.0, transport: httpx.BaseTransport | None = None) -> None:
        auth = (username, password) if username else None
        self.client = httpx.Client(base_url=url.rstrip("/"), auth=auth, timeout=timeout, transport=transport)

    def close(self) -> None:
        self.client.close()

    def _req(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            r = self.client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise BackendUnavailable(f"Orthanc não respondeu: {exc}") from exc
        if r.status_code >= 500:
            raise BackendUnavailable(f"Orthanc respondeu {r.status_code}")
        return r

    def ping(self) -> dict:
        r = self._req("GET", "/system")
        r.raise_for_status()
        j = r.json()
        return {"name": "Orthanc", "version": j.get("Version"), "dicom_aet": j.get("DicomAet"),
                "dicom_port": j.get("DicomPort"), "api_version": j.get("ApiVersion")}

    def store(self, data: bytes) -> StoredRef:
        r = self._req("POST", "/instances", content=data, headers={"Content-Type": "application/dicom"})
        if r.status_code == 400:
            raise ValueError("O Orthanc recusou o arquivo DICOM.")
        r.raise_for_status()
        j = r.json()
        status = j.get("Status", "")
        if status not in ("Success", "AlreadyStored"):
            raise ValueError(f"Orthanc: {status or 'resposta inesperada'}")
        tags = self._req("GET", f"/instances/{j['ID']}/simplified-tags").json()
        return StoredRef(backend_id=j["ID"], sop_uid=tags.get("SOPInstanceUID", ""),
                         already_existed=status == "AlreadyStored")

    def fetch(self, backend_id: str) -> bytes:
        r = self._req("GET", f"/instances/{backend_id}/file")
        if r.status_code == 404:
            raise FileNotFoundError(backend_id)
        r.raise_for_status()
        return r.content

    def changes(self, since: int, limit: int = 100) -> tuple[list[Change], int, bool]:
        r = self._req("GET", "/changes", params={"since": since, "limit": limit})
        r.raise_for_status()
        j = r.json()
        out = [Change(int(c["Seq"]), c["ID"]) for c in j.get("Changes", [])
               if c.get("ChangeType") == "NewInstance" and c.get("ResourceType") == "Instance"]
        return out, int(j.get("Last", since)), bool(j.get("Done", True))

    def origin(self, backend_id: str) -> dict:
        r = self._req("GET", f"/instances/{backend_id}/metadata", params={"expand": ""})
        if r.status_code == 404:
            raise FileNotFoundError(backend_id)
        r.raise_for_status()
        m = {k.lower(): v for k, v in r.json().items()}
        return {"origin": m.get("origin"), "called_aet": (m.get("calledaet") or "").strip() or None,
                "remote_aet": (m.get("remoteaet") or "").strip() or None, "remote_ip": m.get("remoteip")}

    def delete(self, backend_id: str) -> None:
        r = self._req("DELETE", f"/instances/{backend_id}")
        if r.status_code not in (200, 404):
            r.raise_for_status()
