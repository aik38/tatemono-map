"""Observed Ulucks group labels; add only explicit print-heading prefixes."""
import re
import unicodedata

AREA_LABELS = ('小倉北区','小倉南区','八幡東区','八幡西区','若松区','戸畑区','門司区',
    '中間市','遠賀郡','京都郡','行橋市','築上郡','豊前市','直方市','鞍手郡','田川郡',
    '田川市','宗像市','宮若市','飯塚市','嘉穂郡','嘉麻市')
# County membership: https://www.pref.fukuoka.lg.jp/contents/kyuuyo-kouhyou.html
COUNTY_TOWNS = {
    '遠賀郡': ('芦屋町','水巻町','岡垣町','遠賀町'),
    '京都郡': ('苅田町','みやこ町'), '築上郡': ('吉富町','上毛町','築上町'),
    '鞍手郡': ('小竹町','鞍手町'), '嘉穂郡': ('桂川町',),
    '田川郡': ('香春町','添田町','糸田町','川崎町','大任町','赤村','福智町'),
}
AREA_RE = '|'.join(map(re.escape, AREA_LABELS))


def municipality_of(address):
    value = re.sub(r'\s+', '', unicodedata.normalize('NFKC', address or ''))
    value = value.removeprefix('福岡県')
    for label in AREA_LABELS:
        prefix = '北九州市'+label if label.endswith('区') else label
        if value.startswith(prefix):
            if label in COUNTY_TOWNS:
                return next((label+t for t in COUNTY_TOWNS[label] if value.startswith(label+t)), None)
            return prefix
    return None


def complement_print_address(address, heading):
    value = unicodedata.normalize('NFKC', address or '').strip()
    bare = value.removeprefix('福岡県')
    # Some actual prints name the town explicitly but omit its county.
    # Fukuoka's observed group has one official county for each listed town;
    # complete incoming source addresses only, never canonical DB values.
    for county,towns in COUNTY_TOWNS.items():
        if any(bare.startswith(town) for town in towns):
            return ('福岡県' if value.startswith('福岡県') else '')+county+bare
    # A neighbourhood can contain 市 (宮市町 / 西宮市二丁目). A bare
    # occurrence of that character is insufficient to identify another city.
    explicit_city=re.match(r'[^0-9\s-]+?市(?!町|[一二三四五六七八九十0-9]+(?:丁目|番|号))',bare)
    if value.startswith('福岡県') or municipality_of(value) or explicit_city or re.match(r'[^0-9\s-]+?郡',bare):
        return value
    if any(bare.startswith(w) for w in AREA_LABELS if w.endswith('区')):
        return '北九州市'+bare
    if heading in COUNTY_TOWNS:
        if any(bare.startswith(t) for t in COUNTY_TOWNS[heading]):
            return heading+bare
        return value  # Missing a town is insufficient evidence; scope QC stops.
    if heading in AREA_LABELS:
        if any(bare.startswith(t) for towns in COUNTY_TOWNS.values() for t in towns):
            return value  # Never carry the previous ward across a missing county heading.
        return ('北九州市' if heading.endswith('区') else '')+heading+bare
    return value
