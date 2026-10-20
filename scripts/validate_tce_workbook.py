"""Valida a planilha de referência contra os agregados persistidos no Supabase.

Uso:
  python scripts/validate_tce_workbook.py --xlsx "C:\\Users\\User\\Downloads\\COMPRAS MUNICIPAIS - ACARAÚ.xlsx" --municipio 2300200 --ano 2025
"""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from src.tce_expenses import load_municipality_report

NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def _to_decimal(value: str | None) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    text = str(value).strip().replace(".", "").replace(",", ".")
    if text.endswith("%"):
        text = text[:-1]
        try:
            return Decimal(text) / Decimal("100")
        except InvalidOperation:
            return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().upper())


def _sheet_rows(path: Path) -> list[dict[str, str | None]]:
    with ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = [
                "".join(text.text or "" for text in node.findall(".//a:t", NS))
                for node in strings_root.findall("a:si", NS)
            ]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rel_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rels = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rel_root}
        first_sheet = workbook.find("a:sheets/a:sheet", NS)
        if first_sheet is None:
            return []
        target = rels[first_sheet.attrib[f"{{{NS['r']}}}id"]]
        sheet_path = target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"
        root = ET.fromstring(archive.read(sheet_path))
        rows: list[dict[str, str | None]] = []
        for row in root.findall(".//a:sheetData/a:row", NS):
            parsed: dict[str, str | None] = {}
            for cell in row.findall("a:c", NS):
                ref = cell.attrib.get("r", "")
                col = re.match(r"[A-Z]+", ref)
                if not col:
                    continue
                value = cell.find("a:v", NS)
                inline = cell.find("a:is", NS)
                raw = value.text if value is not None else None
                if cell.attrib.get("t") == "s" and raw is not None:
                    raw = shared[int(raw)]
                elif inline is not None:
                    raw = "".join(text.text or "" for text in inline.findall(".//a:t", NS))
                parsed[col.group(0)] = raw
            rows.append(parsed)
        return rows


def parse_workbook(path: Path) -> tuple[dict[str, dict], dict]:
    rows = _sheet_rows(path)
    parsed: dict[str, dict] = {}
    total = {"total": Decimal("0"), "mpe": Decimal("0"), "percent_text": Decimal("0")}
    for row in rows:
        name = (row.get("A") or "").strip()
        if not name:
            continue
        if name.upper().startswith("TOTAL"):
            total = {
                "total": _to_decimal(row.get("B")),
                "mpe": _to_decimal(row.get("C")),
                "percent_text": _to_decimal(row.get("D")),
            }
            continue
        if name.upper().startswith("NATUREZA") or name.upper().startswith("FONTE"):
            continue
        parsed[_normalize_name(name)] = {
            "total": _to_decimal(row.get("B")),
            "mpe": _to_decimal(row.get("C")),
            "percent_text": _to_decimal(row.get("D")),
        }
    return parsed, total


def compare(workbook_rows: dict[str, dict], workbook_total: dict, report: dict) -> list[str]:
    issues: list[str] = []
    report_rows = {
        _normalize_name(row["nature_name"]): row
        for row in report["details"]
    }
    for nature, workbook in sorted(workbook_rows.items()):
        database = report_rows.get(nature)
        if not database:
            issues.append(f"[NATUREZA AUSENTE NO BANCO] {nature}")
            continue
        db_total = Decimal(str(database.get("total_amount") or 0))
        db_mpe = Decimal(str(database.get("mpe_amount") or 0))
        if abs(db_total - workbook["total"]) > Decimal("0.01"):
            issues.append(f"[TOTAL DIVERGENTE] {nature}: planilha={workbook['total']} banco={db_total}")
        if abs(db_mpe - workbook["mpe"]) > Decimal("0.01"):
            issues.append(f"[MPE DIVERGENTE] {nature}: planilha={workbook['mpe']} banco={db_mpe}")
        pct_calc = (workbook["mpe"] / workbook["total"]) if workbook["total"] > 0 else Decimal("0")
        if abs(pct_calc - workbook["percent_text"]) > Decimal("0.001"):
            issues.append(
                f"[PERCENTUAL INCONSISTENTE NA PLANILHA] {nature}: texto={workbook['percent_text']:.4f} calculado={pct_calc:.4f}"
            )
    report_total = Decimal(str(report["summary"].get("total_amount") or 0))
    report_mpe = Decimal(str(report["summary"].get("mpe_amount") or 0))
    if abs(report_total - workbook_total["total"]) > Decimal("0.01"):
        issues.append(f"[TOTAL GERAL DIVERGENTE] planilha={workbook_total['total']} banco={report_total}")
    if abs(report_mpe - workbook_total["mpe"]) > Decimal("0.01"):
        issues.append(f"[MPE GERAL DIVERGENTE] planilha={workbook_total['mpe']} banco={report_mpe}")
    total_percent_calc = (workbook_total["mpe"] / workbook_total["total"]) if workbook_total["total"] > 0 else Decimal("0")
    if abs(total_percent_calc - workbook_total["percent_text"]) > Decimal("0.001"):
        issues.append(
            f"[PERCENTUAL GERAL INCONSISTENTE NA PLANILHA] texto={workbook_total['percent_text']:.4f} calculado={total_percent_calc:.4f}"
        )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", required=True, type=Path)
    parser.add_argument("--municipio", required=True)
    parser.add_argument("--ano", required=True, type=int)
    args = parser.parse_args()

    workbook_rows, workbook_total = parse_workbook(args.xlsx)
    report = load_municipality_report(args.municipio, args.ano)
    if not report:
        print("Relatório não encontrado no banco. Execute primeiro a sincronização TCE para este município/ano.")
        return 2
    issues = compare(workbook_rows, workbook_total, report)
    if not issues:
        print("Validação concluída sem divergências.")
        return 0
    print("Divergências encontradas:")
    for issue in issues:
        print("-", issue)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
