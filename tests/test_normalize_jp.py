from tatemono_map.normalize.jp import normalize_address_jp


def test_normalize_address_jp_absorbs_chome_notation_noise() -> None:
    values = [
        "北九州市門司区葛葉3丁目",
        "北九州市門司区葛葉３丁目",
        "北九州市門司区葛葉三丁目",
        "北九州市門司区葛葉3丁目丁目",
        "北九州市門司区葛葉3-丁目",
    ]

    normalized = {normalize_address_jp(v) for v in values}
    assert normalized == {"福岡県北九州市門司区葛葉3"}


def test_normalize_address_jp_handles_chome_banchi_go_variants() -> None:
    values = [
        "北九州市小倉北区日明三丁目14-12",
        "北九州市小倉北区日明3丁目14-12",
        "北九州市小倉北区日明3-14-12",
    ]

    normalized = {normalize_address_jp(v) for v in values}
    assert normalized == {"福岡県北九州市小倉北区日明3-14-12"}
