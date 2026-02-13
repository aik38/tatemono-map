from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

import pandas as pd
from pypdf import PdfReader

import pdfplumber

FINAL_SCHEMA = [
    "category",
    "updated_at",
    "building_name",
    "room",
    "address",
    "rent_man",
    "fee_man",
    "layout",
    "floor",
    "area_sqm",
    "age_years",
    "structure",
    "file",
    "page",
    "raw_block",
]

LEGACY_SCHEMA = ["source_property_name", "room_no", "raw_blockfile"]

BAD_BUILDING_TOKENS = ["》", "号", "NEW"]
DETACHED_HOUSE_KEYWORDS = ["戸建", "一戸建", "貸家", "一軒家"]
WARD_NAMES = ["門司区", "小倉北区", "小倉南区", "戸畑区", "八幡東区", "八幡西区", "若松区"]
WARD_RE = "|".join(WARD_NAMES)
REALPRO_CONTEXT_INNER_BAND_PX = 60.0

REALPRO_TABLE_HEADER_TOKENS = ["号室名", "賃料", "共益費", "間取", "面積", "敷金", "礼金", "管理費"]


@dataclass
class DetectResult:
    kind: str
    reason: str


@dataclass
class ParseResult:
    df: pd.DataFrame
    warnings: List[str]
    drop_reasons: Dict[str, int]


class VacancyParser(Protocol):
    name: str

    def detect_kind(self, first_page_text: str, metadata: Dict[str, Any]) -> DetectResult:
        ...

    def parse(self, pdf_path: Path) -> ParseResult:
        ...


def nfkc(s: Any) -> str:
    if s is None:
        return ""
    s = str(s)
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u3000", " ")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[‐-–—−－]", "-", s)
    s = s.replace("（", "(").replace("）", ")").replace("【", "[").replace("】", "]")
    return s.strip()


def is_mojibake(text: Any) -> bool:
    src = "" if text is None else str(text)
    if not src:
        return False
    n = len(src)
    jp = len(re.findall(r"[ぁ-んァ-ン一-龥]", src))
    rep = src.count("�")
    mojisig = len(re.findall(r"[ãÃÂ¢€œ]", src))
    jp_ratio = jp / n if n else 0.0
    rep_ratio = rep / n if n else 0.0
    mojisig_ratio = mojisig / n if n else 0.0
    return jp_ratio < 0.01 or rep_ratio >= 0.01 or mojisig_ratio >= 0.03


def restore_latin1_cp932_mojibake(text: Any) -> str:
    src = "" if text is None else str(text)
    if not src:
        return ""
    try:
        fixed = src.encode("latin1").decode("cp932")
    except Exception:
        return src
    src_jp = len(re.findall(r"[ぁ-んァ-ン一-龥]", src))
    fixed_jp = len(re.findall(r"[ぁ-んァ-ン一-龥]", fixed))
    return fixed if fixed_jp > src_jp else src


def normalize_pdf_text(text: Any) -> str:
    src = "" if text is None else str(text)
    if is_mojibake(src):
        src = restore_latin1_cp932_mojibake(src)
    return nfkc(src)


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
    if s == "" or s in {"-", "—", "–", "無", "なし"}:
        return float("nan")
    s = s.replace("税込", "").replace("税別", "")
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*万", s)
    if m:
        return float(m.group(1))
    s = s.replace("円", "")
    s = re.sub(r"[^\d.,]", "", s).replace(",", "")
    if s == "":
        return float("nan")
    try:
        return float(s) / 10000.0
    except Exception:
        return float("nan")


def parse_area_sqm(x: Any) -> float:
    s = nfkc(x).replace("㎡", "").replace("m2", "")
    s = re.sub(r"[^\d.]", "", s)
    if s == "":
        return float("nan")
    try:
        return float(s)
    except Exception:
        return float("nan")


def classify_detached_house(name: str) -> bool:
    s = nfkc(name)
    return any(k in s for k in DETACHED_HOUSE_KEYWORDS)


def split_building_and_room(name: str, room: str = "") -> Tuple[str, str]:
    src = nfkc(name)
    room_existing = nfkc(room)
    if not src:
        return "", room_existing
    if room_existing:
        return src, room_existing

    if re.search(r"([A-ZＡ-Ｚ]|[IVXⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]|\d+)\s*号?棟$|[東西南北]\s*棟$", src):
        return src, ""

    explicit_patterns = [
        r"^(.*?)[\s\-]+(\d{2,4})\s*号室$",
        r"^(.*?)[\s\-]+(\d{2,4})\s*号$",
        r"^(.*?)[\s\-]+(\d\-\d{2})$",
        r"^(.*?)\((\d{2,4})\)$",
    ]
    for pat in explicit_patterns:
        m = re.match(pat, src)
        if m:
            b = nfkc(m.group(1))
            r = nfkc(m.group(2)).replace("-", "")
            if b and r:
                return b, r

    if re.search(r"[\s\-]\d{2,4}$", src):
        m = re.match(r"^(.*?)[\s\-](\d{2,4})$", src)
        if m:
            return nfkc(m.group(1)), nfkc(m.group(2))

    return src, ""


def apply_name_and_row_filters(df: pd.DataFrame) -> Tuple[pd.DataFrame, int, Dict[str, int]]:
    if len(df) == 0:
        out = df.copy()
        out["source_property_name"] = ""
        out["room_no"] = ""
        return out, 0, {"detached_house": 0}

    out = df.copy()
    out["source_property_name"] = out["building_name"].fillna("").astype(str).map(nfkc)
    out["room"] = out.get("room", "").fillna("").astype(str).map(nfkc)

    split_pairs = [split_building_and_room(n, r) for n, r in zip(out["source_property_name"], out["room"])]
    out["building_name"] = [t[0] for t in split_pairs]
    out["room_no"] = [t[1] for t in split_pairs]

    detached_mask = out["source_property_name"].map(classify_detached_house)
    dropped = int(detached_mask.sum())
    out = out.loc[~detached_mask].copy()
    return out, dropped, {"detached_house": dropped}


def looks_like_money(s: str) -> bool:
    s = nfkc(s)
    return bool(re.search(r"\d{1,3}(,\d{3})+", s)) or ("円" in s) or ("万" in s)


def is_noise_line(line: str) -> bool:
    s = nfkc(line)
    if not s:
        return True
    patterns = [
        r"TEL[:：]",
        r"FAX[:：]",
        r"^\d+/\d+頁$",
        r"^\d+/\d+ページ$",
        r"^\d+/\d+$",
        r"空室一覧表",
        r"^\d{4}[/-]\d{1,2}[/-]\d{1,2}",
        r"^\d{1,2}:\d{2}",
        r"北九州市.*区$",
        r"号室名をクリック",
        r"リアプロにログイン",
        r"詳細情報のウェブページ",
    ]
    return any(re.search(p, s, flags=re.IGNORECASE) for p in patterns)


def is_table_header_like_line(line: str) -> bool:
    s = nfkc(line)
    if not s:
        return False
    return any(tok in s for tok in REALPRO_TABLE_HEADER_TOKENS)


def clean_realpro_address_line(line: str) -> str:
    s = nfkc(line)
    if "/" in s:
        s = s.split("/", 1)[0]
    if "／" in s:
        s = s.split("／", 1)[0]
    return nfkc(s)


def looks_like_address(line: str) -> bool:
    s = nfkc(line)
    return bool(re.search(r"(都|道|府|県|市|区|町|村).*(丁目|番地|番|号|\d+-\d+)", s))


def looks_like_structure_or_age(line: str) -> bool:
    s = nfkc(line)
    return bool(re.search(r"(RC|SRC|S造|木造|鉄骨|鉄筋|築\d+年|築年)", s))


def extract_ward_hint(text: str) -> str:
    s = nfkc(text)
    m = re.search(rf"({WARD_RE})", s)
    return m.group(1) if m else ""


def complement_address_with_ward(address: str, ward_hint: str) -> str:
    addr = nfkc(address)
    ward = nfkc(ward_hint)
    if not addr:
        return addr
    if re.search(rf"北九州市(?:{WARD_RE})", addr):
        return addr
    if not ward:
        return addr
    if addr.startswith("北九州市") and ward in addr:
        return addr
    if addr.startswith(ward):
        return f"北九州市{addr}"
    return f"北九州市{ward}{addr}"


class UlucksParser:
    name = "ulucks"

    def detect_kind(self, first_page_text: str, metadata: Dict[str, Any]) -> DetectResult:
        score = 0
        t = normalize_pdf_text(first_page_text)
        if "ウラックス" in t:
            score += 2
        if "空室一覧" in t:
            score += 2
        for tok in ["物件名", "号室", "賃料", "間取", "㎡"]:
            if tok in t:
                score += 1
        return DetectResult(kind="ulucks" if score >= 4 else "non_vacancy", reason=f"ulucks_score={score}")

    def parse(self, pdf_path: Path) -> ParseResult:
        rows: List[Dict[str, Any]] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for pi, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                text = normalize_pdf_text(text)
                updated = parse_updated_at(text)
                ward_hint = extract_ward_hint(text)
                tables = page.extract_tables() or []
                for tb in tables:
                    if not tb or len(tb) < 2:
                        continue
                    header = [normalize_pdf_text(c) for c in tb[0]]
                    if not ("物件名" in header and "号室" in header and "賃料" in header):
                        continue
                    idx = {h: header.index(h) for h in header if h}
                    for r in tb[1:]:
                        if not r or all(normalize_pdf_text(c) == "" for c in r):
                            continue
                        r = list(r) + [None] * (len(header) - len(r))
                        building = normalize_pdf_text(r[idx.get("物件名", "")])
                        address = normalize_pdf_text(r[idx.get("所在地", "")])
                        address = complement_address_with_ward(address, ward_hint)
                        room = normalize_pdf_text(r[idx.get("号室", "")])
                        room = re.sub(r"\s*《.*?》\s*", "", room).strip()
                        layout_detail = normalize_pdf_text(r[idx.get("間取詳細", "")])
                        layout = nfkc(layout_detail.split(":")[0]) if layout_detail else ""
                        raw = f"[source=ulucks file={pdf_path.name} page={pi}] " + "|".join(normalize_pdf_text(c) for c in r if normalize_pdf_text(c) != "")
                        rows.append(
                            {
                                "page": pi,
                                "category": "ulucks",
                                "updated_at": updated,
                                "building_name": building,
                                "room": room,
                                "address": address,
                                "rent_man": parse_money_to_man(r[idx.get("賃料", "")]),
                                "fee_man": parse_money_to_man(r[idx.get("共益費", "")]),
                                "floor": "",
                                "layout": layout,
                                "area_sqm": parse_area_sqm(r[idx.get("面積", "")]),
                                "age_years": float("nan"),
                                "structure": normalize_pdf_text(r[idx.get("構造", "")]),
                                "file": pdf_path.name,
                                "raw_block": raw,
                                "raw_blockfile": raw,
                            }
                        )
        df = pd.DataFrame(rows)
        return ParseResult(df=df, warnings=[], drop_reasons={})


class RealproParser:
    name = "realpro"

    def detect_kind(self, first_page_text: str, metadata: Dict[str, Any]) -> DetectResult:
        score = 0
        t = normalize_pdf_text(first_page_text)
        for tok in ["リアプロ", "空室一覧表", "号室名", "賃料", "管理費"]:
            if tok in t:
                score += 1
        return DetectResult(kind="realpro" if score >= 3 else "non_vacancy", reason=f"realpro_score={score}")

    def _extract_contexts(self, lines: List[str]) -> List[Tuple[str, str, str, float]]:
        context = self._extract_context_from_lines(lines, extract_ward_hint(" ".join(lines)))
        return [context] if context[0] else []

    def _extract_context_from_lines(self, lines: List[str], ward_hint: str = "") -> Tuple[str, str, str, float]:
        if not lines:
            return "", "", "", float("nan")
        local_ward_hint = extract_ward_hint(" ".join(lines)) or ward_hint
        building = ""
        for line in lines:
            s = nfkc(line)
            if not s or is_noise_line(s):
                continue
            if is_table_header_like_line(s):
                continue
            if looks_like_address(s):
                continue
            if looks_like_structure_or_age(s):
                continue
            if "空室" in s or "一覧" in s:
                continue
            building = s
            break

        address = ""
        for line in lines:
            s = nfkc(line)
            if looks_like_address(s):
                address = complement_address_with_ward(clean_realpro_address_line(s), local_ward_hint)
                break

        nearby = " ".join(lines)
        structure = ""
        age = float("nan")
        sm = re.search(r"(RC|SRC|S造|木造|鉄骨造|鉄筋コンクリート造)", nearby)
        if sm:
            structure = sm.group(1)
        am = re.search(r"(?:築\s*(\d+)\s*年|(\d{4})年\s*(\d{1,2})月\s*築)", nearby)
        if am and am.group(1):
            age = float(am.group(1))
        return building, address, structure, age

    def _words_to_lines(self, words: List[Dict[str, Any]]) -> List[str]:
        if not words:
            return []
        rows: Dict[int, List[Dict[str, Any]]] = {}
        for w in words:
            top = float(w.get("top", 0.0))
            key = int(round(top / 4.0))
            rows.setdefault(key, []).append(w)
        out: List[str] = []
        for key in sorted(rows.keys()):
            row_words = sorted(rows[key], key=lambda x: float(x.get("x0", 0.0)))
            line = nfkc(" ".join(nfkc(w.get("text", "")) for w in row_words if nfkc(w.get("text", ""))))
            if line:
                out.append(line)
        return out

    def _extract_context_for_table(self, page: Any, table_bbox: Tuple[float, float, float, float], prev_bottom: float, ward_hint: str) -> Tuple[str, str, str, float]:
        top = float(table_bbox[1]) if table_bbox else 0.0
        bottom = float(table_bbox[3]) if table_bbox else top
        context_bottom = min(top + REALPRO_CONTEXT_INNER_BAND_PX, bottom)
        if context_bottom <= prev_bottom:
            return "", "", "", float("nan")
        words = page.extract_words(x_tolerance=2, y_tolerance=2) or []
        block_words = [
            w
            for w in words
            if prev_bottom <= float(w.get("top", 0.0)) <= context_bottom and float(w.get("top", 0.0)) >= 50.0
        ]
        lines = self._words_to_lines(block_words)
        return self._extract_context_from_lines(lines, ward_hint)

    def parse(self, pdf_path: Path) -> ParseResult:
        rows: List[Dict[str, Any]] = []
        warns: List[str] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for pi, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                text = normalize_pdf_text(text)
                updated = parse_updated_at(text)
                ward_hint = extract_ward_hint(text)

                page_tables = page.find_tables() or []
                if not page_tables:
                    for tb in page.extract_tables() or []:
                        class _T:
                            def __init__(self, t):
                                self._t = t
                                self.bbox = (0.0, 0.0, 0.0, 10000.0)
                            def extract(self):
                                return self._t
                        page_tables.append(_T(tb))

                prev_bottom = 0.0
                last_context: Tuple[str, str, str, float] = ("", "", "", float("nan"))
                for t in sorted(page_tables, key=lambda x: float(x.bbox[1]) if getattr(x, "bbox", None) else 0.0):
                    tb = t.extract() or []
                    if not tb or len(tb) < 2:
                        prev_bottom = float(t.bbox[3]) if getattr(t, "bbox", None) else prev_bottom
                        continue
                    header_row = None
                    header = []
                    for hi in range(min(3, len(tb))):
                        row = [normalize_pdf_text(c) for c in tb[hi] if c is not None]
                        if "号室名" in row and "賃料" in row:
                            header_row = hi
                            header = [normalize_pdf_text(c) for c in tb[hi]]
                            break
                    if header_row is None:
                        prev_bottom = float(t.bbox[3]) if getattr(t, "bbox", None) else prev_bottom
                        continue
                    idx = {h: header.index(h) for h in header if h}

                    bbox = t.bbox if getattr(t, "bbox", None) else (0.0, prev_bottom, 0.0, prev_bottom)
                    context = self._extract_context_for_table(page, bbox, prev_bottom, ward_hint)
                    if not context[0] and last_context[0]:
                        context = last_context
                    if not context[0]:
                        warns.append(f"p{pi}:building_context_not_found")
                    if context[0]:
                        last_context = context

                    for r in tb[header_row + 1 :]:
                        if not r or all(normalize_pdf_text(c) == "" for c in r):
                            continue
                        r = list(r) + [None] * (len(header) - len(r))
                        roomcell = normalize_pdf_text(r[idx.get("号室名", "")])
                        rentcell = normalize_pdf_text(r[idx.get("賃料", "")])
                        if roomcell == "" and rentcell == "":
                            continue
                        room_m = re.search(r"(\d{2,4})", roomcell)
                        room = room_m.group(1) if room_m else roomcell
                        floor_m = re.search(r"(\d+)\s*階", roomcell)
                        floor = floor_m.group(1) if floor_m else ""
                        la = normalize_pdf_text(r[idx.get("間取・面積", "")])
                        layout = ""
                        area = float("nan")
                        lm = re.search(r"(\d+[A-Z]*LDK|\d+DK|\d+K|1R)", la)
                        if lm:
                            layout = lm.group(1)
                        am = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:㎡|m2)", la)
                        if am:
                            area = float(am.group(1))
                        raw = f"[source=realpro file={pdf_path.name} page={pi}] " + "|".join(normalize_pdf_text(c) for c in r if normalize_pdf_text(c) != "")
                        rows.append(
                            {
                                "page": pi,
                                "category": "realpro",
                                "updated_at": updated,
                                "file": pdf_path.name,
                                "building_name": context[0],
                                "room": room,
                                "address": context[1],
                                "rent_man": parse_money_to_man(r[idx.get("賃料", "")]),
                                "fee_man": parse_money_to_man(r[idx.get("共益費", "")]),
                                "floor": floor,
                                "layout": layout,
                                "area_sqm": area,
                                "age_years": context[3],
                                "structure": context[2],
                                "raw_block": raw,
                                "raw_blockfile": raw,
                            }
                        )
                    prev_bottom = float(t.bbox[3]) if getattr(t, "bbox", None) else prev_bottom

        df = pd.DataFrame(rows)
        bad_mask = df.get("building_name", pd.Series(dtype=str)).fillna("").map(
            lambda s: bool(re.search(r"TEL|FAX|^\d+/\d+頁$", nfkc(s)))
        )
        if len(df) and bad_mask.any():
            warns.append(f"building_name_noise_rows={int(bad_mask.sum())}")
        if len(df) and (df["address"].fillna("") == "").any():
            warns.append("address_empty_rows")
        return ParseResult(df=df, warnings=warns, drop_reasons={})


PARSERS: Sequence[VacancyParser] = [UlucksParser(), RealproParser()]


def detect_pdf_kind(path: Path) -> DetectResult:
    first = ""
    try:
        r = PdfReader(str(path))
        if r.pages:
            first = normalize_pdf_text(r.pages[0].extract_text() or "")
    except Exception:
        first = ""
    if not first:
        try:
            with pdfplumber.open(str(path)) as pdf:
                first = normalize_pdf_text(pdf.pages[0].extract_text() or "")
        except Exception as e:
            return DetectResult("non_vacancy", f"sniff_error:{type(e).__name__}")

    meta = {"filename": path.name}
    results = [p.detect_kind(first, meta) for p in PARSERS]
    matched = [r for r in results if r.kind != "non_vacancy"]
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        return DetectResult("non_vacancy", "ambiguous_kind")
    return DetectResult("non_vacancy", ";".join(r.reason for r in results))


def dedupe(df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    before = len(df)
    key_cols = ["category", "building_name", "address", "room", "rent_man", "fee_man", "floor", "layout", "area_sqm"]
    df2 = df.drop_duplicates(subset=key_cols, keep="first")
    return df2, before - len(df2)


def qc_check(df: pd.DataFrame, category: str) -> List[str]:
    reasons: List[str] = []
    if len(df) == 0:
        return ["extracted_rows=0"]

    bn = df["building_name"].fillna("").astype(str).map(nfkc)
    bad = bn.map(
        lambda s: (len(s) <= 2)
        or bool(re.fullmatch(r"\d{2,4}", s))
        or any(tok in s for tok in BAD_BUILDING_TOKENS if not (tok == "号" and "棟" in s))
    )
    bad_ratio = float(bad.mean()) if len(bad) else 0.0
    if bad_ratio >= 0.20:
        reasons.append(f"building_name_bad_ratio={bad_ratio:.2f}")

    if category == "realpro" and bn.map(lambda s: bool(re.search(r"TEL|FAX|^\d+/\d+頁$", s))).any():
        reasons.append("building_name_contains_noise")

    addr = df["address"].fillna("").astype(str)
    if addr.map(looks_like_money).any():
        reasons.append("address_looks_like_money")
    if (addr.map(nfkc) == "").any():
        reasons.append("address_empty")

    if category in {"ulucks", "realpro"}:
        room = df["room"].fillna("").astype(str).map(nfkc)
        empty_ratio = float((room == "").mean())
        if empty_ratio >= 0.50:
            reasons.append(f"room_empty_ratio={empty_ratio:.2f}")

    if category == "realpro":
        has_room = df["room"].fillna("").astype(str).map(nfkc) != ""
        empty_name = df["building_name"].fillna("").astype(str).map(nfkc) == ""
        if (has_room & empty_name).any():
            reasons.append("building_name_missing_with_room")

    return reasons


def should_stop_on_qc_failures(qc_mode: str, failures: int) -> bool:
    return qc_mode == "strict" and failures > 0


def write_csv(df: pd.DataFrame, path: Path, *, legacy_columns: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = FINAL_SCHEMA + (LEGACY_SCHEMA if legacy_columns else [])
    df = df.reindex(columns=schema)
    df.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\r\n", quoting=csv.QUOTE_ALL, na_rep="")


def _extract_with_parser(kind: str, path: Path) -> ParseResult:
    parser = next((p for p in PARSERS if p.name == kind), None)
    if parser is None:
        return ParseResult(df=pd.DataFrame([], columns=FINAL_SCHEMA + LEGACY_SCHEMA), warnings=["unsupported_kind"], drop_reasons={})
    return parser.parse(path)


def _try_parse_ambiguous(path: Path) -> Tuple[str, Optional[ParseResult]]:
    for kind in ("realpro", "ulucks"):
        parsed = _extract_with_parser(kind, path)
        if len(parsed.df) > 0:
            return kind, parsed
    return "non_vacancy", None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ulucks-dir", required=False, default="")
    ap.add_argument("--realpro-dir", required=False, default="")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--qc-mode", choices=["strict", "warn", "off"], default="warn")
    ap.add_argument("--legacy-columns", action="store_true")
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
        except Exception:
            pages = 0

        detect = detect_pdf_kind(path)
        kind = detect.kind
        manifest_rows.append(
            {
                "file": path.name,
                "sha256": sha,
                "bytes": path.stat().st_size,
                "pages": pages,
                "kind": kind,
                "classify_reason": detect.reason,
            }
        )

        parsed: Optional[ParseResult] = None
        if kind == "non_vacancy" and detect.reason == "ambiguous_kind":
            recovered_kind, recovered = _try_parse_ambiguous(path)
            if recovered is not None:
                kind = recovered_kind
                parsed = recovered

        if kind == "non_vacancy":
            qc_lines.append(f"[WARN] {path.name} kind=non_vacancy reason={detect.reason}")
            stats_rows.append(
                {
                    "file": path.name,
                    "sha256": sha,
                    "pages": pages,
                    "kind": kind,
                    "extracted_rows": 0,
                    "drop_reasons": "",
                    "warning_count": 1,
                    "status": "WARN",
                    "reasons": detect.reason,
                }
            )
            return

        if parsed is None:
            parsed = _extract_with_parser(kind, path)
        df = parsed.df
        extracted_row_count = len(df)
        df, dropped_rows, drop_reasons = apply_name_and_row_filters(df)
        df, dup_removed = dedupe(df)
        per_path = per_pdf_dir / f"{sha}.csv"
        write_csv(df, per_path, legacy_columns=args.legacy_columns)

        reasons: List[str] = []
        status = "SKIP" if args.qc_mode == "off" else "OK"
        if args.qc_mode != "off":
            reasons = qc_check(df, kind)
            reasons.extend(parsed.warnings)
            status = "OK" if not reasons else "WARN"

        if reasons:
            qc_lines.append(f"[WARN] {path.name} kind={kind} reasons={';'.join(reasons)}")
        if should_stop_on_qc_failures(args.qc_mode, 1 if reasons else 0):
            failures += 1

        stats_rows.append(
            {
                "file": path.name,
                "sha256": sha,
                "pages": pages,
                "kind": kind,
                "extracted_rows": len(df),
                "drop_reasons": ";".join(f"{k}:{v}" for k, v in drop_reasons.items() if v),
                "warning_count": len(reasons),
                "status": status,
                "dedupe_removed": dup_removed,
                "source_extracted_rows": extracted_row_count,
                "reasons": ";".join(reasons),
            }
        )
        all_dfs.append(df)

    for root in [args.ulucks_dir, args.realpro_dir]:
        if root:
            for p in sorted(Path(root).rglob("*.pdf")):
                handle_pdf(p)

    pd.DataFrame(manifest_rows).to_csv(out_dir / "manifest.csv", index=False, encoding="utf-8-sig", lineterminator="\r\n", quoting=csv.QUOTE_ALL)
    pd.DataFrame(stats_rows).to_csv(out_dir / "stats.csv", index=False, encoding="utf-8-sig", lineterminator="\r\n", quoting=csv.QUOTE_ALL)
    (out_dir / "qc_report.txt").write_text("\r\n".join(qc_lines) + ("\r\n" if qc_lines else ""), encoding="utf-8-sig")

    if should_stop_on_qc_failures(args.qc_mode, failures):
        print(f"[STOP] QC warnings treated as failures: {failures}", file=sys.stderr)
        return 2

    merged = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame([], columns=FINAL_SCHEMA + LEGACY_SCHEMA)
    merged, _ = dedupe(merged)
    write_csv(merged, out_dir / "final.csv", legacy_columns=args.legacy_columns)
    print(f"[OK] final.csv rows={len(merged)} -> {out_dir / 'final.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
