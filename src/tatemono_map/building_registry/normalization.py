from __future__ import annotations

from dataclasses import dataclass

from tatemono_map.normalize.jp import normalize_address_jp, normalize_building_name


PREFECTURE_PREFIXES = (
    "北海道",
    "青森県",
    "岩手県",
    "宮城県",
    "秋田県",
    "山形県",
    "福島県",
    "茨城県",
    "栃木県",
    "群馬県",
    "埼玉県",
    "千葉県",
    "東京都",
    "神奈川県",
    "新潟県",
    "富山県",
    "石川県",
    "福井県",
    "山梨県",
    "長野県",
    "岐阜県",
    "静岡県",
    "愛知県",
    "三重県",
    "滋賀県",
    "京都府",
    "大阪府",
    "兵庫県",
    "奈良県",
    "和歌山県",
    "鳥取県",
    "島根県",
    "岡山県",
    "広島県",
    "山口県",
    "徳島県",
    "香川県",
    "愛媛県",
    "高知県",
    "福岡県",
    "佐賀県",
    "長崎県",
    "熊本県",
    "大分県",
    "宮崎県",
    "鹿児島県",
    "沖縄県",
)


@dataclass(frozen=True)
class NormalizedBuilding:
    raw_name: str
    raw_address: str
    normalized_name: str
    normalized_address: str


def strip_prefecture_prefix(address: str | None) -> str:
    value = (address or "").strip()
    for prefix in PREFECTURE_PREFIXES:
        if value.startswith(prefix):
            return value[len(prefix) :]
    return value


def normalize_building_input(name: str | None, address: str | None) -> NormalizedBuilding:
    raw_name = (name or "").strip()
    raw_address = (address or "").strip()
    return NormalizedBuilding(
        raw_name=raw_name,
        raw_address=raw_address,
        normalized_name=normalize_building_name(raw_name),
        normalized_address=strip_prefecture_prefix(normalize_address_jp(raw_address)),
    )
