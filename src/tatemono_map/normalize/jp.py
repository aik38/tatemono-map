from __future__ import annotations

import re
import unicodedata

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
