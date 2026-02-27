from __future__ import annotations

import re
import unicodedata

RE_MULTI_SPACE = re.compile(r"\s+")
RE_ROOM_SUFFIX = re.compile(r"(?:\s|#|-|－)?\d{1,4}[A-Za-z]?(?:号?室?)$")
RE_HYPHENS = re.compile(r"[‐‑‒–—―ーｰ－]+")
RE_CHOME_NOISY = re.compile(r"(\d+)\s*-?\s*(?:丁目)+")
RE_CHOME = re.compile(r"(\d+)\s*-?\s*丁目")
RE_BANCHI = re.compile(r"(\d+)番地?")
RE_GO = re.compile(r"(\d+)号")
RE_KANJI_NUM = re.compile(r"([〇零一二三四五六七八九十百]+)(?=(?:\s*-?\s*(?:丁目|番地?|番|号)))")


def _kanji_number_to_int(token: str) -> int | None:
    digits = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if not token:
        return None
    if token == "十":
        return 10

    total = 0
    if "百" in token:
        left, right = token.split("百", 1)
        if left and left not in digits:
            return None
        total += (digits.get(left, 1) if left else 1) * 100
        token = right

    if "十" in token:
        left, right = token.split("十", 1)
        if left and left not in digits:
            return None
        total += (digits.get(left, 1) if left else 1) * 10
        token = right

    if token:
        if token not in digits:
            return None
        total += digits[token]

    return total


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

    def _replace_kanji_number(match: re.Match[str]) -> str:
        num = _kanji_number_to_int(match.group(1))
        return str(num) if num is not None else match.group(1)

    text = RE_KANJI_NUM.sub(_replace_kanji_number, text)
    if text.startswith("北九州市"):
        text = f"福岡県{text}"
    text = text.replace("福岡県北九州市北九州市", "福岡県北九州市")

    text = RE_CHOME_NOISY.sub(r"\1丁目", text)
    text = RE_CHOME.sub(r"\1-", text)
    text = RE_BANCHI.sub(r"\1-", text)
    text = RE_GO.sub(r"\1", text)
    text = re.sub(r"丁目|番地|番|号", "", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text
