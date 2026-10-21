"""Converte falhas de um relatório JUnit (pytest) em anotações do GitHub Actions (::error)."""

import sys
import xml.etree.ElementTree as ET

for path in sys.argv[1:]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        print(f"::warning::{path}: {exc}")
        continue
    for tc in root.iter("testcase"):
        for kind in ("failure", "error"):
            for f in tc.findall(kind):
                text = ((f.get("message") or "") + "\n" + (f.text or ""))[-3500:]
                text = text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
                print(f"::error title={tc.get('classname')}.{tc.get('name')}::{text}")
