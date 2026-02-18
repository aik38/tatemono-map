import sqlite3
from tatemono_map.parse.smartlink_page import parse_and_upsert

db = r"data/tatemono_map.sqlite3"

# 1) パース実行（raw_sources.smartlink_page -> listings）
n = parse_and_upsert(db)
print("parse_and_upsert:", n)

# 2) 監査
con = sqlite3.connect(db)
def one(sql):
    return con.execute(sql).fetchone()[0]

print("raw_sources.smartlink_page=", one("select count(*) from raw_sources where source_kind='smartlink_page'"))
print("raw_sources.smartview     =", one("select count(*) from raw_sources where source_kind='smartview'"))
print("listings.total            =", one("select count(*) from listings"))
print("listings.with_address     =", one("select count(*) from listings where address is not null and address != ''"))
print("listings.with_rent_yen    =", one("select count(*) from listings where rent_yen is not null"))
print("listings.with_room_label  =", one("select count(*) from listings where room_label is not null and room_label != ''"))
con.close()
