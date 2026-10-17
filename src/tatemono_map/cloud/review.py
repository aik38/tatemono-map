"""Apply explicit human decisions to a private disposable master copy."""
import argparse
import csv
import json
from pathlib import Path

from tatemono_map.cloud.pipeline import validate_master
from tatemono_map.cloud.partial import confirm_review
from tatemono_map.db.repo import connect


def apply_decisions(master, decisions):
    validate_master(master)
    with decisions.open(encoding='utf-8-sig',newline='') as stream:
        rows=[row for row in csv.DictReader(stream) if row.get('decision','').strip()]
    # One transaction: an incomplete confirmation rolls back the entire file.
    with connect(master) as conn:
        for row in rows:
            confirm_review(conn,row['review_key'],row['decision'],row.get('building_id') or None,
                row.get('room_label',''),row.get('reviewer',''))
    return len(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',required=True,type=Path)
    parser.add_argument('--decisions',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps({'explicit_review_decisions':apply_decisions(args.db,args.decisions)}))


if __name__=='__main__':main()
