"""DEPRECATED: not used in current canonical workflow; kept only for reference.

Use scripts/weekly_update.ps1 and the building_registry pipeline for canonical operations.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

RE_MULTI_SPACE = re.compile(r"\s+")
RE_ROOM_SUFFIX = re.compile(r"(?:\s|#|-|－)?\d{1,4}[A-Za-z]?(?:号?室?)$")
RE_HYPHENS = re.compile(r"[‐‑‒–—―ーｰ－]+")
RE_CHOME = re.compile(r"(\d+)丁目")
RE_BANCHI = re.compile(r"(\d+)番地?")
RE_GO = re.compile(r"(\d+)号")


def _nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def normalize_building_name(value: str) -> str:
    text = _nfkc(value).strip()
    text = RE_MULTI_SPACE.sub(" ", text)
    text = RE_HYPHENS.sub("-", text)
    text = text.replace("･", "・")
    text = RE_ROOM_SUFFIX.sub("", text).strip(" -")
    return text


def normalize_address_jp(value: str) -> str:
    text = _nfkc(value).strip()
    text = RE_MULTI_SPACE.sub("", text)
    text = RE_HYPHENS.sub("-", text)
    if text.startswith("北九州市"):
        text = f"福岡県{text}"
    text = text.replace("福岡県北九州市北九州市", "福岡県北九州市")
    text = RE_CHOME.sub(r"\1-", text)
    text = RE_BANCHI.sub(r"\1-", text)
    text = RE_GO.sub(r"\1", text)
    text = text.replace("番", "-")
    text = re.sub(r"-+", "-", text).strip("-")
    return text


def _is_weak_address(normalized_address: str) -> bool:
    if not normalized_address:
        return True
    if not re.search(r"\d", normalized_address):
        return True
    if re.search(r"\d+-$", normalized_address):
        return True
    return not bool(re.search(r"\d+-\d+", normalized_address))


def _is_suspicious_name(normalized_name: str) -> bool:
    if not normalized_name:
        return True
    if len(normalized_name) <= 1:
        return True
    return bool(re.fullmatch(r"[\d\-]+", normalized_name))


def _stable_key(normalized_address: str, normalized_name: str) -> str:
    material = f"{normalized_address}|{normalized_name}".encode("utf-8")
    return hashlib.sha1(material).hexdigest()[:16]


def _pick(row: dict[str, str], *columns: str) -> str:
    for col in columns:
        v = (row.get(col) or "").strip()
        if v:
            return v
    return ""


def _collect_pdf_evidence(row: dict[str, str]) -> str:
    important = [
        "source_pdf",
        "source_id",
        "reference_url",
        "source_url",
        "pdf_name",
        "file_name",
        "row_id",
    ]
    vals: list[str] = []
    for key in important:
        val = (row.get(key) or "").strip()
        if val:
            vals.append(f"{key}:{val}")
    if vals:
        return " | ".join(vals)

    for key in sorted(row.keys()):
        if "source" in key.lower() or "pdf" in key.lower() or "ref" in key.lower():
            val = (row.get(key) or "").strip()
            if val:
                vals.append(f"{key}:{val}")
    return " | ".join(vals)


@dataclass
class Candidate:
    source: str
    building_name: str
    address: str
    normalized_building_name: str
    normalized_address: str
    building_key: str
    evidence_url_or_id: str
    reason_codes: list[str]


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"CSV header missing: {path}")
        return [{k: (v or "") for k, v in row.items()} for row in reader]


def _dedup_mansion_review(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: dict[str, dict[str, str]] = {}
    for i, row in enumerate(rows):
        key = (row.get("detail_url") or "").strip() or f"__row_{i}"
        deduped.setdefault(key, row)
    return list(deduped.values())


def _dedup_pdf(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: dict[str, dict[str, str]] = {}
    for i, row in enumerate(rows):
        key = _collect_pdf_evidence(row) or f"__row_{i}"
        deduped.setdefault(key, row)
    return list(deduped.values())


def _build_candidates(pdf_rows: list[dict[str, str]], mr_rows: list[dict[str, str]]) -> list[Candidate]:
    candidates: list[Candidate] = []

    for row in pdf_rows:
        name = _pick(row, "building_name", "mansion_name")
        address = _pick(row, "address")
        n_name = normalize_building_name(name)
        n_addr = normalize_address_jp(address)
        reasons: list[str] = []
        if not n_addr:
            reasons.append("missing_address")
        elif _is_weak_address(n_addr):
            reasons.append("weak_address")
        if _is_suspicious_name(n_name):
            reasons.append("suspicious_name")
        candidates.append(
            Candidate(
                source="pdf_pipeline",
                building_name=name,
                address=address,
                normalized_building_name=n_name,
                normalized_address=n_addr,
                building_key=_stable_key(n_addr, n_name),
                evidence_url_or_id=_collect_pdf_evidence(row),
                reason_codes=reasons,
            )
        )

    for row in mr_rows:
        name = _pick(row, "building_name", "mansion_name")
        address = _pick(row, "address")
        detail_url = (row.get("detail_url") or "").strip()
        n_name = normalize_building_name(name)
        n_addr = normalize_address_jp(address)
        reasons = []
        if not n_addr:
            reasons.append("missing_address")
        elif _is_weak_address(n_addr):
            reasons.append("weak_address")
        if _is_suspicious_name(n_name):
            reasons.append("suspicious_name")
        candidates.append(
            Candidate(
                source="mansion_review",
                building_name=name,
                address=address,
                normalized_building_name=n_name,
                normalized_address=n_addr,
                building_key=_stable_key(n_addr, n_name),
                evidence_url_or_id=detail_url,
                reason_codes=reasons,
            )
        )

    return candidates


def _apply_conflict_reasons(candidates: list[Candidate]) -> None:
    by_addr: dict[str, set[str]] = defaultdict(set)
    for row in candidates:
        if row.normalized_address:
            by_addr[row.normalized_address].add(row.normalized_building_name)

    for row in candidates:
        if row.normalized_address and len(by_addr[row.normalized_address]) > 1 and "name_conflict_same_address" not in row.reason_codes:
            row.reason_codes.append("name_conflict_same_address")

    by_key: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in candidates:
        by_key[row.building_key].add((row.normalized_address, row.normalized_building_name))
    for row in candidates:
        if len(by_key[row.building_key]) > 1 and "key_collision" not in row.reason_codes:
            row.reason_codes.append("key_collision")


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def run(pdf_csv: Path, mr_csv: Path, out_dir: Path, overrides_csv: Path | None = None) -> dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)

    pdf_rows_input = _load_csv(pdf_csv)
    mr_rows_input = _load_csv(mr_csv)
    pdf_rows = _dedup_pdf(pdf_rows_input)
    mr_rows = _dedup_mansion_review(mr_rows_input)

    candidates = _build_candidates(pdf_rows, mr_rows)
    _apply_conflict_reasons(candidates)

    raw_rows = [
        {
            "source": c.source,
            "building_name": c.building_name,
            "address": c.address,
            "normalized_building_name": c.normalized_building_name,
            "normalized_address": c.normalized_address,
            "building_key": c.building_key,
            "evidence_url_or_id": c.evidence_url_or_id,
            "reason_codes": ";".join(sorted(set(c.reason_codes))),
        }
        for c in candidates
    ]

    keys_group: dict[str, dict[str, object]] = {}
    for row in raw_rows:
        item = keys_group.setdefault(
            str(row["building_key"]),
            {
                "building_key": row["building_key"],
                "normalized_address": row["normalized_address"],
                "normalized_building_name": row["normalized_building_name"],
                "sources": set(),
                "evidence": set(),
                "row_count": 0,
                "reason_codes": set(),
            },
        )
        item["sources"].add(str(row["source"]))
        if row["evidence_url_or_id"]:
            item["evidence"].add(str(row["evidence_url_or_id"]))
        if row["reason_codes"]:
            item["reason_codes"].update(str(row["reason_codes"]).split(";"))
        item["row_count"] = int(item["row_count"]) + 1

    key_rows = [
        {
            "building_key": v["building_key"],
            "normalized_address": v["normalized_address"],
            "normalized_building_name": v["normalized_building_name"],
            "sources": "+".join(sorted(v["sources"])),
            "evidence_count": len(v["evidence"]),
            "row_count": v["row_count"],
            "reason_codes": ";".join(sorted(x for x in v["reason_codes"] if x)),
        }
        for v in keys_group.values()
    ]

    suspect_rows = [row for row in raw_rows if row["reason_codes"]]

    overrides_rows: list[dict[str, str]] = []
    seen_override_keys: set[tuple[str, str]] = set()
    for row in suspect_rows:
        key = (str(row["source"]), str(row["evidence_url_or_id"]))
        if key in seen_override_keys:
            continue
        seen_override_keys.add(key)
        overrides_rows.append(
            {
                "source": str(row["source"]),
                "evidence_url_or_id": str(row["evidence_url_or_id"]),
                "building_key": str(row["building_key"]),
                "building_name_override": "",
                "address_override": "",
                "ignore_flag": "",
                "note": str(row["reason_codes"]),
            }
        )

    overrides_map_by_evidence: dict[tuple[str, str], dict[str, str]] = {}
    overrides_map_by_key: dict[tuple[str, str], dict[str, str]] = {}
    if overrides_csv and overrides_csv.exists():
        for row in _load_csv(overrides_csv):
            src = (row.get("source") or "").strip()
            ev = (row.get("evidence_url_or_id") or "").strip()
            bkey = (row.get("building_key") or "").strip()
            if src and ev:
                overrides_map_by_evidence[(src, ev)] = row
            if src and bkey:
                overrides_map_by_key[(src, bkey)] = row

    primary_order = {"pdf_pipeline": 0, "mansion_review": 1}

    merged_candidates: dict[str, dict[str, object]] = {}
    for row in raw_rows:
        source = str(row["source"])
        key = (source, str(row["evidence_url_or_id"]))
        override = overrides_map_by_evidence.get(key)
        if not override:
            override = overrides_map_by_key.get((source, str(row["building_key"])))
        if override and (override.get("ignore_flag") or "").strip().lower() in {"1", "true", "yes", "y"}:
            continue

        row_name = str(row["building_name"])
        row_addr = str(row["address"])
        if override:
            row_name = (override.get("building_name_override") or "").strip() or row_name
            row_addr = (override.get("address_override") or "").strip() or row_addr

        n_name = normalize_building_name(row_name)
        n_addr = normalize_address_jp(row_addr)
        reasons = []
        if not n_addr:
            reasons.append("missing_address")
        elif _is_weak_address(n_addr):
            reasons.append("weak_address")
        if _is_suspicious_name(n_name):
            reasons.append("suspicious_name")
        if reasons:
            continue

        bkey = _stable_key(n_addr, n_name)
        if bkey not in merged_candidates:
            merged_candidates[bkey] = {
                "building_key": bkey,
                "building_name": row_name,
                "address": row_addr,
                "normalized_building_name": n_name,
                "normalized_address": n_addr,
                "sources": {str(row["source"])},
                "evidence": {str(row["evidence_url_or_id"])} if row["evidence_url_or_id"] else set(),
                "primary_source": str(row["source"]),
            }
        else:
            current = merged_candidates[bkey]
            current["sources"].add(str(row["source"]))
            if row["evidence_url_or_id"]:
                current["evidence"].add(str(row["evidence_url_or_id"]))
            if primary_order.get(str(row["source"]), 99) < primary_order.get(str(current["primary_source"]), 99):
                current["building_name"] = row_name
                current["address"] = row_addr
                current["primary_source"] = str(row["source"])

    merged_rows = [
        {
            "building_key": v["building_key"],
            "building_name": v["building_name"],
            "address": v["address"],
            "normalized_building_name": v["normalized_building_name"],
            "normalized_address": v["normalized_address"],
            "source": "+".join(sorted(v["sources"])),
            "primary_source": v["primary_source"],
            "evidence_url_or_id": " | ".join(sorted(x for x in v["evidence"] if x)),
        }
        for v in merged_candidates.values()
    ]
    merged_rows.sort(key=lambda r: (str(r["normalized_address"]), str(r["normalized_building_name"])))

    master_rows = [
        {
            "building_key": row["building_key"],
            "building_name": row["building_name"],
            "address": row["address"],
            "source": row["source"],
            "evidence_url_or_id": row["evidence_url_or_id"],
        }
        for row in merged_rows
    ]

    _write_csv(
        out_dir / "legacy_master_rebuild_raw.csv",
        [
            "source",
            "building_name",
            "address",
            "normalized_building_name",
            "normalized_address",
            "building_key",
            "evidence_url_or_id",
            "reason_codes",
        ],
        raw_rows,
    )
    _write_csv(
        out_dir / "legacy_master_rebuild_keys.csv",
        [
            "building_key",
            "normalized_address",
            "normalized_building_name",
            "sources",
            "evidence_count",
            "row_count",
            "reason_codes",
        ],
        sorted(key_rows, key=lambda r: str(r["building_key"])),
    )
    _write_csv(
        out_dir / "legacy_master_rebuild_suspects.csv",
        [
            "source",
            "building_name",
            "address",
            "normalized_building_name",
            "normalized_address",
            "building_key",
            "evidence_url_or_id",
            "reason_codes",
        ],
        suspect_rows,
    )
    _write_csv(
        out_dir / "legacy_master_rebuild_overrides.template.csv",
        [
            "source",
            "evidence_url_or_id",
            "building_key",
            "building_name_override",
            "address_override",
            "ignore_flag",
            "note",
        ],
        [
            {
                "source": row["source"],
                "evidence_url_or_id": row["evidence_url_or_id"],
                "building_key": row["building_key"],
                "building_name_override": row["building_name_override"],
                "address_override": row["address_override"],
                "ignore_flag": row["ignore_flag"],
                "note": row["note"],
            }
            for row in overrides_rows
        ],
    )
    _write_csv(
        out_dir / "legacy_master_rebuild_merged_primary_wins.csv",
        [
            "building_key",
            "building_name",
            "address",
            "normalized_building_name",
            "normalized_address",
            "source",
            "primary_source",
            "evidence_url_or_id",
        ],
        merged_rows,
    )
    _write_csv(
        out_dir / "legacy_master_rebuild.csv",
        ["building_key", "building_name", "address", "source", "evidence_url_or_id"],
        master_rows,
    )

    stats = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "pdf_final_csv": str(pdf_csv),
            "mansion_review_uniq_csv": str(mr_csv),
            "overrides_csv": str(overrides_csv) if overrides_csv else "",
        },
        "counts": {
            "pdf_input_rows": len(pdf_rows_input),
            "pdf_dedup_rows": len(pdf_rows),
            "mansion_review_input_rows": len(mr_rows_input),
            "mansion_review_dedup_rows": len(mr_rows),
            "raw_rows": len(raw_rows),
            "suspect_rows": len(suspect_rows),
            "merged_rows": len(merged_rows),
            "master_rows": len(master_rows),
        },
    }
    (out_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build buildings master from pdf final.csv and mansion-review uniq csv")
    parser.add_argument("--pdf-final-csv", required=True)
    parser.add_argument("--mansion-review-uniq-csv", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--overrides-csv", default="")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    overrides = Path(args.overrides_csv) if args.overrides_csv else None
    stats = run(
        pdf_csv=Path(args.pdf_final_csv),
        mr_csv=Path(args.mansion_review_uniq_csv),
        out_dir=Path(args.out_dir),
        overrides_csv=overrides,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
