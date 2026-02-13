# src/tatemono_map/cli/pdf_batch_run.py
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

# PDF libs
import pdfplumber
from pypdf import PdfReader

SCHEMA = [
    "page","category","updated_at","building_name","room","address",
    "rent_man","fee_man","floor","layout","area_sqm","age_years","structure",
    "raw_block","file",
]

BAD_BUILDING_TOKENS = ["》", "号", "NEW"]

def nfkc(s: Any) -> str:
    if s is None:
        return ""
    s = str(s)
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u3000", " ")
    s = re.sub(r"\s+", " ", s)
    # hyphens -> "-"
    s = re.sub(r"[‐-–—−－]", "-", s)
    # brackets
    s = s.replace("（","(").replace("）",")").replace("【","[").replace("】","]")
    return s.strip()

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def page_count_fast(path: Path) -> int:
    r = PdfReader(str(path))
    return len(r.pages)

def parse_updated_at(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"(\d{4})年\s*(\d{2})月\s*(\d{2})日", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"(\d{4})/(\d{2})/(\d{2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""

def parse_money_to_man(x: Any) -> float:
    s = nfkc(x)
    if s == "" or s in {"-","—","–","無","なし"}:
        return float("nan")
    s = s.replace("税込","").replace("税別","")
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*万", s)
    if m:
        return float(m.group(1))
    s = s.replace("円","")
    s = re.sub(r"[^\d.,]", "", s).replace(",", "")
    if s == "":
        return float("nan")
    try:
        return float(s) / 10000.0
    except:
        return float("nan")

def parse_area_sqm(x: Any) -> float:
    s = nfkc(x).replace("㎡","").replace("m2","")
    s = re.sub(r"[^\d.]", "", s)
    if s == "":
        return float("nan")
    try:
        return float(s)
    except:
        return float("nan")

def looks_like_money(s: str) -> bool:
    s = nfkc(s)
    return bool(re.search(r"\d{1,3}(,\d{3})+", s)) or ("円" in s) or ("万" in s)

def classify_pdf(path: Path) -> Tuple[str,str]:
    name = path.name
    if "オリエント" in name or "ORIENT" in name.upper():
        return "orient", "filename"
    # lightweight sniff
    try:
        with pdfplumber.open(str(path)) as pdf:
            p = pdf.pages[0]
            text = p.extract_text() or ""
            t = nfkc(text)
            if "空室一覧表" in t and "号室名" in t:
                return "realpro", "text:空室一覧表/号室名"
            if "CLUB ORIENT" in t or "ORIENT BLD" in t:
                return "orient", "text:ORIENT"
            # ulucks often has "物件名/号室/賃料" in table header
            tables = p.extract_tables() or []
            for tb in tables:
                if not tb or len(tb) < 2:
                    continue
                header = [nfkc(c) for c in tb[0]]
                if "物件名" in header and "号室" in header and "賃料" in header:
                    return "ulucks", "table:物件名/号室/賃料"
    except Exception as e:
        return "unknown", f"sniff_error:{type(e).__name__}"
    return "unknown", "no_match"

def ulucks_extract(path: Path) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    with pdfplumber.open(str(path)) as pdf:
        for pi, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            updated = parse_updated_at(text)
            try:
                tables = page.extract_tables() or []
            except Exception as e:
                # if table extraction fails, treat as 0 rows -> QC fail later
                tables = []

            for tb in tables:
                if not tb or len(tb) < 2:
                    continue
                header = [nfkc(c) for c in tb[0]]
                if not ("物件名" in header and "号室" in header and "賃料" in header):
                    continue
                idx = {h: header.index(h) for h in header if h}

                for r in tb[1:]:
                    if not r or all(nfkc(c) == "" for c in r):
                        continue
                    r = list(r) + [None] * (len(header) - len(r))
                    building = nfkc(r[idx.get("物件名","")])
                    address  = nfkc(r[idx.get("所在地","")])
                    room     = nfkc(r[idx.get("号室","")])
                    room     = re.sub(r"\s*《.*?》\s*", "", room).strip()

                    layout_detail = nfkc(r[idx.get("間取詳細","")])
                    layout = nfkc(layout_detail.split(":")[0]) if layout_detail else ""

                    rent = parse_money_to_man(r[idx.get("賃料","")])
                    fee  = parse_money_to_man(r[idx.get("共益費","")])
                    area = parse_area_sqm(r[idx.get("面積","")])

                    structure = nfkc(r[idx.get("構造","")])
                    age_years = float("nan")
                    age_cell = nfkc(r[idx.get("築年","")])
                    m = re.search(r"\((\d+)\s*年\)", age_cell)
                    if m:
                        age_years = float(m.group(1))

                    raw = f"[source=ulucks file={path.name} page={pi}] " + "|".join(nfkc(c) for c in r if nfkc(c) != "")
                    rows.append({
                        "page": pi,
                        "category": "ulucks",
                        "updated_at": updated,
                        "building_name": building,
                        "room": room,
                        "address": address,
                        "rent_man": rent,
                        "fee_man": fee,
                        "floor": "",
                        "layout": layout,
                        "area_sqm": area,
                        "age_years": age_years,
                        "structure": structure,
                        "raw_block": raw,
                        "file": path.name,
                    })
    return pd.DataFrame(rows, columns=SCHEMA)

def realpro_extract(path: Path) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    with pdfplumber.open(str(path)) as pdf:
        for pi, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            lines = [nfkc(l) for l in text.splitlines() if nfkc(l)]
            updated = parse_updated_at(text)

            # building header (北九州市... line)
            bname, addr = "", ""
            addr_idx = None
            for i, l in enumerate(lines):
                if "北九州市" in l and ("区" in l) and ("／" in l or "/" in l):
                    addr_idx = i
                    break
            if addr_idx is not None and addr_idx > 0:
                bname = lines[addr_idx - 1]
                addr = lines[addr_idx].split("／")[0].strip()

            structure = ""
            age_years = float("nan")
            for l in lines:
                if "造" in l and "築" in l:
                    m = re.search(r"(.+?造)", l)
                    if m:
                        structure = m.group(1)
                    # age_years is optional; keep blank unless you really want to compute
                    break

            tables = []
            try:
                tables = page.extract_tables() or []
            except Exception:
                tables = []

            for tb in tables:
                if not tb or len(tb) < 3:
                    continue
                header_row = None
                header = []
                for hi in range(min(3, len(tb))):
                    row = [nfkc(c) for c in tb[hi] if c is not None]
                    if "号室名" in row and "賃料" in row:
                        header_row = hi
                        header = [nfkc(c) for c in tb[hi]]
                        break
                if header_row is None:
                    continue
                idx = {h: header.index(h) for h in header if h}

                last: Optional[Dict[str, Any]] = None
                for r in tb[header_row + 1:]:
                    if not r or all(nfkc(c) == "" for c in r):
                        continue
                    r = list(r) + [None] * (len(header) - len(r))

                    roomcell = nfkc(r[idx.get("号室名","")])
                    rentcell = nfkc(r[idx.get("賃料","")])

                    # continuation rows (room/rent empty)
                    if roomcell == "" and rentcell == "" and last is not None:
                        cont = "|".join(nfkc(c) for c in r if nfkc(c) != "")
                        last["raw_block"] += " || " + cont
                        continue

                    m = re.search(r"(\d{2,4})", roomcell)
                    room = m.group(1) if m else roomcell
                    fm = re.search(r"(\d+)\s*階", roomcell)
                    floor = fm.group(1) if fm else ""

                    la = nfkc(r[idx.get("間取・面積","")])
                    layout = ""
                    area = float("nan")
                    lm = re.search(r"(\d+[A-Z]*LDK|\d+DK|\d+K|1R)", la)
                    if lm:
                        layout = lm.group(1)
                    am = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:㎡|m2)", la)
                    if am:
                        area = float(am.group(1))

                    rent = parse_money_to_man(r[idx.get("賃料","")])
                    fee  = parse_money_to_man(r[idx.get("共益費","")])

                    raw = f"[source=realpro file={path.name} page={pi}] " + "|".join(nfkc(c) for c in r if nfkc(c) != "")
                    last = {
                        "page": pi,
                        "category": "realpro",
                        "updated_at": updated,
                        "building_name": nfkc(bname),
                        "room": room,
                        "address": nfkc(addr),
                        "rent_man": rent,
                        "fee_man": fee,
                        "floor": floor,
                        "layout": layout,
                        "area_sqm": area,
                        "age_years": age_years,
                        "structure": nfkc(structure),
                        "raw_block": raw,
                        "file": path.name,
                    }
                    rows.append(last)

    return pd.DataFrame(rows, columns=SCHEMA)

def orient_extract(path: Path) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    bname_pat = re.compile(r"(CLUB ORIENT No\.\d+\s+[^\n]+|ORIENT BLD No\.\d+\s+[^\n]+)")
    with pdfplumber.open(str(path)) as pdf:
        for pi, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            updated = parse_updated_at(text)
            norm = "\n".join(nfkc(l) for l in text.splitlines())

            matches = list(bname_pat.finditer(norm))
            for i, m in enumerate(matches):
                start = m.start()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(norm)
                chunk = norm[start:end]

                bname = nfkc(m.group(1))
                am = re.search(r"(北九州市[^\n]+)", chunk)
                addr = nfkc(am.group(1)) if am else ""

                # choose the “big” parentheses (not (株))
                infos = re.findall(r"\((.*?)\)", chunk, flags=re.S)
                best = ""
                for inner in infos:
                    inner_nf = nfkc(inner)
                    if any(k in inner_nf for k in ["HRC","SRC","RC","鉄","木","免震","階","戶","戸"]):
                        if len(inner_nf) > len(best):
                            best = inner_nf

                structure = ""
                layouts: List[str] = []
                if best:
                    sm = re.search(r"\b(HRC|SRC|RC|S)\s*\d+階", best)
                    if sm:
                        structure = sm.group(0).replace(" ", "")
                    for lay in re.findall(r"\b\d+[A-Z]*LDK\b|\b\d+DK\b|\b\d+K\b|\b1R\b", best):
                        layouts.append(lay)

                raw = f"[source=orient file={path.name} page={pi}] " + chunk.replace("\n", " ")
                if bname and addr:
                    rows.append({
                        "page": pi,
                        "category": "orient",
                        "updated_at": updated,
                        "building_name": bname,
                        "room": "",
                        "address": addr,
                        "rent_man": float("nan"),
                        "fee_man": float("nan"),
                        "floor": "",
                        "layout": "/".join(sorted(set(layouts))),
                        "area_sqm": float("nan"),
                        "age_years": float("nan"),
                        "structure": structure,
                        "raw_block": raw,
                        "file": path.name,
                    })

    return pd.DataFrame(rows, columns=SCHEMA)

def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # enforce schema & order
    df = df.reindex(columns=SCHEMA)
    df.to_csv(
        path,
        index=False,
        encoding="utf-8-sig",
        line_terminator="\r\n",
        quoting=csv.QUOTE_ALL,
        na_rep="",
    )

def qc_check(df: pd.DataFrame, category: str) -> List[str]:
    reasons: List[str] = []
    if len(df) == 0:
        return ["extracted_rows=0"]

    # building_name garbage ratio
    bn = df["building_name"].fillna("").astype(str).map(nfkc)
    bad = bn.map(lambda s: (len(s) <= 2) or any(tok in s for tok in BAD_BUILDING_TOKENS))
    bad_ratio = float(bad.mean()) if len(bad) else 0.0
    if bad_ratio >= 0.20:
        reasons.append(f"building_name_bad_ratio={bad_ratio:.2f}")

    # address looks like money
    addr = df["address"].fillna("").astype(str)
    if addr.map(looks_like_money).any():
        reasons.append("address_looks_like_money")

    # room mostly empty (ulucks/realpro only)
    if category in {"ulucks","realpro"}:
        room = df["room"].fillna("").astype(str).map(nfkc)
        empty_ratio = float((room == "").mean())
        if empty_ratio >= 0.50:
            reasons.append(f"room_empty_ratio={empty_ratio:.2f}")

    return reasons

def dedupe(df: pd.DataFrame) -> Tuple[pd.DataFrame,int]:
    before = len(df)
    key_cols = ["file","building_name","address","room","rent_man","fee_man","floor","layout","area_sqm"]
    df2 = df.drop_duplicates(subset=key_cols, keep="first")
    return df2, before - len(df2)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ulucks-dir", required=False, default="")
    ap.add_argument("--realpro-dir", required=False, default="")
    ap.add_argument("--orient-pdf", required=False, default="")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows = []
    per_pdf_dir = out_dir / "per_pdf"
    stats_rows = []
    qc_lines: List[str] = []

    all_dfs: List[pd.DataFrame] = []
    failures = 0

    def handle_pdf(path: Path) -> None:
        nonlocal failures
        sha = sha256_file(path)
        pages = 0
        try:
            pages = page_count_fast(path)
        except Exception as e:
            pages = 0

        category, reason = classify_pdf(path)
        manifest_rows.append({
            "file": path.name,
            "sha256": sha,
            "bytes": path.stat().st_size,
            "pages": pages,
            "category": category,
            "classify_reason": reason,
        })

        if category == "ulucks":
            df = ulucks_extract(path)
        elif category == "realpro":
            df = realpro_extract(path)
        elif category == "orient":
            df = orient_extract(path)
        else:
            df = pd.DataFrame([], columns=SCHEMA)

        df, dup_removed = dedupe(df)

        per_path = per_pdf_dir / f"{sha}.csv"
        write_csv(df, per_path)

        reasons = qc_check(df, category)
        status = "OK" if not reasons else "FAIL"
        if status == "FAIL":
            failures += 1
            qc_lines.append(f"[FAIL] {path.name} sha256={sha} category={category} reasons={';'.join(reasons)}")
            # dump minimal fixture for debugging (text + first-page tables)
            fx = out_dir / "fixtures" / sha
            fx.mkdir(parents=True, exist_ok=True)
            try:
                with pdfplumber.open(str(path)) as pdf:
                    p0 = pdf.pages[0]
                    (fx / "page1.txt").write_text(p0.extract_text() or "", encoding="utf-8")
                    tables = p0.extract_tables() or []
                    (fx / "page1_tables.txt").write_text(str(tables)[:20000], encoding="utf-8")
            except Exception as e:
                (fx / "fixture_error.txt").write_text(repr(e), encoding="utf-8")

        buildings = df["building_name"].fillna("").astype(str).map(nfkc)
        rooms = df["room"].fillna("").astype(str).map(nfkc)

        stats_rows.append({
            "file": path.name,
            "sha256": sha,
            "pages": pages,
            "category": category,
            "extracted_rows": len(df),
            "buildings": int((buildings != "").sum()) and int(buildings.nunique()) or 0,
            "vacancies": int((rooms != "").sum()),
            "dedupe_removed": int(dup_removed),
            "status": status,
            "reasons": ";".join(reasons),
        })

        all_dfs.append(df)

    # collect inputs
    if args.ulucks_dir:
        for p in sorted(Path(args.ulucks_dir).rglob("*.pdf")):
            handle_pdf(p)
    if args.realpro_dir:
        for p in sorted(Path(args.realpro_dir).rglob("*.pdf")):
            handle_pdf(p)
    if args.orient_pdf:
        handle_pdf(Path(args.orient_pdf))

    # write manifest / stats / qc
    pd.DataFrame(manifest_rows).to_csv(out_dir / "manifest.csv", index=False, encoding="utf-8-sig", line_terminator="\r\n", quoting=csv.QUOTE_ALL)
    pd.DataFrame(stats_rows).to_csv(out_dir / "stats.csv", index=False, encoding="utf-8-sig", line_terminator="\r\n", quoting=csv.QUOTE_ALL)
    (out_dir / "qc_report.txt").write_text("\r\n".join(qc_lines) + ("\r\n" if qc_lines else ""), encoding="utf-8-sig")

    if failures:
        print(f"[STOP] QC failed: {failures} pdf(s). See: {out_dir/'qc_report.txt'}", file=sys.stderr)
        return 2

    # merge
    merged = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame([], columns=SCHEMA)
    merged, dup_removed = dedupe(merged)
    write_csv(merged, out_dir / "final.csv")
    print(f"[OK] final.csv rows={len(merged)} (dup_removed={dup_removed}) -> {out_dir/'final.csv'}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
