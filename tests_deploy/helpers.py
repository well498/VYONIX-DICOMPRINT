"""Passos de teste do motor (arquivos reais numa pasta temporária)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from vyonix_deploy.engine import Context, Step


class FileStep(Step):
    """Garante um arquivo com conteúdo. Conta quantas vezes foi aplicado (arquivo .count)."""

    category = "armazenamento"

    def __init__(self, key: str, path: Path, content: str, *, fail_verify: bool = False, wait_for: Path | None = None,
                 started: Path | None = None) -> None:
        self.id = f"file.{key}"
        self.title = f"Arquivo {key}"
        self.path = Path(path)
        self.content = content
        self.fail_verify = fail_verify
        self.wait_for = wait_for
        self.started = started

    def observe(self, ctx: Context) -> dict:
        return {"exists": self.path.exists(), "content": self.path.read_text() if self.path.exists() else None}

    def desired(self, ctx: Context) -> dict:
        return {"content": self.content}

    def check(self, ctx: Context) -> bool:
        return self.path.exists() and self.path.read_text() == self.content

    def apply(self, ctx: Context) -> None:
        cnt = self.path.with_suffix(".count")
        cnt.write_text(str(int(cnt.read_text()) + 1 if cnt.exists() else 1))
        if self.started:
            self.started.write_text("1")
        if self.wait_for:
            while not self.wait_for.exists():
                time.sleep(0.05)
        self.path.write_text(self.content)

    def verify(self, ctx: Context):
        if self.fail_verify:
            return False, "simulação de falha de verificação (teste)"
        return super().verify(ctx)

    def rollback(self, ctx: Context, before: dict) -> None:
        if before.get("exists"):
            self.path.write_text(before["content"])
        elif self.path.exists():
            os.remove(self.path)

    def applied(self) -> int:
        cnt = self.path.with_suffix(".count")
        return int(cnt.read_text()) if cnt.exists() else 0


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
