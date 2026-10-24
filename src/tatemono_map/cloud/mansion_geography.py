"""The existing 22 publication areas, expanded to all 35 municipalities.

IDs are resolved against the provider's fresh prefecture catalogs, never
guessed from a missing link. Keep this configuration independent of crawling.
"""
AREAS = {
    '門司区': ['北九州市門司区'], '小倉北区': ['北九州市小倉北区'],
    '小倉南区': ['北九州市小倉南区'], '戸畑区': ['北九州市戸畑区'],
    '若松区': ['北九州市若松区'], '八幡東区': ['北九州市八幡東区'],
    '八幡西区': ['北九州市八幡西区'], '中間市': ['中間市'],
    '遠賀郡': ['遠賀郡芦屋町','遠賀郡水巻町','遠賀郡岡垣町','遠賀郡遠賀町'],
    '行橋市': ['行橋市'], '京都郡': ['京都郡苅田町','京都郡みやこ町'],
    '豊前市': ['豊前市'], '築上郡': ['築上郡吉富町','築上郡上毛町','築上郡築上町'],
    '直方市': ['直方市'], '宮若市': ['宮若市'], '飯塚市': ['飯塚市'],
    '田川市': ['田川市'], '嘉麻市': ['嘉麻市'],
    '鞍手郡': ['鞍手郡小竹町','鞍手郡鞍手町'],
    '田川郡': ['田川郡香春町','田川郡添田町','田川郡糸田町','田川郡川崎町','田川郡大任町','田川郡赤村','田川郡福智町'],
    '嘉穂郡': ['嘉穂郡桂川町'], '宗像市': ['宗像市'],
}
MUNICIPALITIES = tuple(m for towns in AREAS.values() for m in towns)


def municipality(address):
    import re, unicodedata
    value = re.sub(r'\s+', '', unicodedata.normalize('NFKC', address or '')).removeprefix('福岡県')
    return next((m for m in MUNICIPALITIES if value.startswith(m)), None)
