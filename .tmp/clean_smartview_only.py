import sqlite3
db = r"data/tatemono_map.sqlite3"
con = sqlite3.connect(db)
cur = con.cursor()
cur.execute("DELETE FROM listings WHERE source_url LIKE '%/view/smartview/%'")
cur.execute("DELETE FROM raw_sources WHERE source_kind='smartview'")
con.commit()
print("cleaned smartview rows:",
      "listings_deleted=", cur.rowcount)
con.close()
