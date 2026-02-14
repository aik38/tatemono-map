# scripts/buildings_master_from_mr_chintai.py
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


def _norm_text(s: str) -> str:
    s = "" if s is None else str(s)
    s = unicodedata.normalize("NFKC", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _norm_addr(addr: str) -> str:
    a = _norm_text(addr)
    # unify hyphens
    a = a.replace("−", "-").replace("―", "-").replace("‐", "-").replace("ー", "-")
    # japanese address tokens -> more stable key
    a = a.replace("番地", "-").replace("番", "-").replace("号", "")
    a = a.replace("丁目", "-")
    # remove spaces
    a = re.sub(r"[ 　]", "", a)
    # collapse multiple hyphens
    a = re.sub(r"-{2,}", "-", a)
    return a


_NOISE_PATTERNS = [
    re.compile(r".*賃貸マンション.*ランキング.*"),
    re.compile(r".*賃貸マンション.*アパート.*情報検索.*"),
]


def _clean_building_name(name: str) -> str:
    n = _norm_text(name)
    if not n:
        return ""
    for pat in _NOISE_PATTERNS:
        if pat.match(n):
            return ""
    # strip trailing obvious room suffix like "101号室" (if it ever appears)
    n = re.sub(r"(?:\s|　)*(?:\d{1,4})(?:号室|号|室)\s*$", "", n).strip()
    return n


def _key(addr_norm: str, name_norm: str) -> str:
    h = hashlib.sha1(f"{addr_norm}|{name_norm}".encode("utf-8")).hexdigest()
    return h[:16]


def _pick_first(row: dict, keys: List[str]) -> str:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            v = _norm_text(row[k])
            if v:
                return v
    return ""


def build_master(rows: Iterable[dict]) -> Tuple[List[str], List[dict]]:
    # schema-flexible: accept either building_name or mansion_name
    out_rows: Dict[str, dict] = {}

    for r in rows:
        name = _pick_first(r, ["building_name", "mansion_name", "name"])
        addr = _pick_first(r, ["address", "addr"])

        name = _clean_building_name(name)
        addr_norm = _norm_addr(addr)
        name_norm = _norm_text(name)

        if not name_norm or not addr_norm:
            continue

        k = _key(addr_norm, name_norm)

        if k not in out_rows:
            out_rows[k] = {
                "building_key": k,
                "building_name": name,
                "address": _norm_text(addr),
                "address_norm": addr_norm,
                "building_name_norm": name_norm,
                "access": _pick_first(r, ["access"]),
                "built": _pick_first(r, ["built"]),
                "floors": _pick_first(r, ["floors"]),
                "units": _pick_first(r, ["units"]),
                "detail_url": _pick_first(r, ["detail_url", "url"]),
                "city_id": _pick_first(r, ["city_id"]),
                "source": "mansion_review_chintai",
                "vacancy_rows": 0,
                "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

        out_rows[k]["vacancy_rows"] += 1

        # if we later see richer values, keep first-non-empty
        for col in ["access", "built", "floors", "units", "detail_url", "city_id"]:
            if not out_rows[k].get(col):
                v = _pick_first(r, [col])
                if v:
                    out_rows[k][col] = v

    header = [
        "building_key",
        "building_name",
        "address",
        "access",
        "built",
        "floors",
        "units",
        "detail_url",
        "city_id",
        "source",
        "vacancy_rows",
        "address_norm",
        "building_name_norm",
        "scraped_at",
    ]
    return header, list(out_rows.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="input chintai CSV (rows may be vacancies)")
    ap.add_argument("--out", dest="out", required=True, help="output building master CSV")
    args = ap.parse_args()

    inp = Path(args.inp)
    out = Path(args.out)

    with inp.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header, rows = build_master(reader)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"[DONE] buildings={len(rows)} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
