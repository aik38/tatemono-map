from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from tatemono_map.building_registry.seed_from_ui import seed_from_ui_csv
from tatemono_map.cloud.public_db import sha256
from tatemono_map.cloud.storage import commit_release
from tatemono_map.db.repo import connect
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.cloud.public_db import export_public


@pytest.fixture
def config():
    return {'login_url': 'https://kitakyushu.ulucks.jp/', 'search_url': 'https://kitakyushu.ulucks.jp/company/lists/8', 'company_id': '8', 'company_label': '株式会社不動産中央情報センター', 'area_id': 'kokurakita', 'area_label': '小倉北区', 'address_contains': '小倉北区', 'baseline_listing_keys': [], 'baseline_reviewed': True, 'max_rows': 5000, 'max_drop_ratio': 0.25, 'auto_seed_high_confidence': False}


@pytest.fixture
def master(tmp_path):
    seed = tmp_path / "seed.csv"
    seed.write_text("building_name,address,evidence_url_or_id,merge_to_evidence\n架空テストマンション,福岡県北九州市小倉北区魚町1-1-1,test:a,\n他社テストマンション,福岡県北九州市門司区港町2-2-2,test:b,\n", encoding="utf-8")
    path = tmp_path / "master.sqlite3"
    seed_from_ui_csv(str(path), str(seed))
    with connect(path) as conn:
        b = conn.execute("SELECT building_id FROM buildings WHERE canonical_name='他社テストマンション'").fetchone()[0]
        conn.execute("INSERT INTO listings(listing_key,building_key,name,address,room_label,rent_yen,source_kind) VALUES ('legacy-b',?,'他社テストマンション','福岡県北九州市門司区港町2-2-2','202',70000,'realpro')", (b,))
    rebuild(str(path))
    return path


def make_pdf(path: Path, rent="5.5万円", address="福岡県北九州市小倉北区魚町1-1-1", rooms=("101",)):
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    rows = [["物件名", "号室", "所在地", "賃料", "共益費", "間取詳細", "面積", "築年月", "構造", "入居時期"]]
    rows += [["架空テストマンション", room, address, rent, "0.3万円", "1K:洋室", "25.0㎡", "2015年3月", "RC", "即入居"] for room in rooms]
    table = Table(rows, colWidths=[115, 35, 230, 60, 60, 65, 50, 75, 35, 55])
    table.setStyle(TableStyle([("FONTNAME", (0,0),(-1,-1), "HeiseiKakuGo-W5"), ("FONTSIZE", (0,0),(-1,-1), 9), ("GRID", (0,0),(-1,-1), 0.5, colors.black)]))
    SimpleDocTemplate(str(path), pagesize=(1000, 400)).build([table])
    return path


@pytest.fixture
def pdf(tmp_path):
    return make_pdf(tmp_path / "ulucks-000.pdf")


class MemoryStore:
    """Generation-checked fake, preserving production storage semantics."""
    def __init__(self, root):
        self.root = root
        root.mkdir()
        self.objects = {}
        self.head = None
        self.generation = 0
        self.fail_upload_prefix = None
        self.fail_commit = False
        self.downloads = []

    def upload(self, path, name):
        if self.fail_upload_prefix and name.startswith(self.fail_upload_prefix):
            raise RuntimeError("simulated upload failure")
        if name in self.objects:
            raise RuntimeError("precondition failed")
        target = self.root / str(len(self.objects))
        shutil.copyfile(path, target)
        ref = {"object": name, "generation": len(self.objects) + 1, "sha256": sha256(target)}
        self.objects[name] = (ref, target)
        return ref

    def download(self, ref, output):
        self.downloads.append(ref["object"])
        stored, path = self.objects[ref["object"]]
        assert stored == ref
        shutil.copyfile(path, output)

    def upload_verified(self, path, name):
        if name in self.objects:
            ref, stored = self.objects[name]
            if sha256(stored) != sha256(path):
                raise RuntimeError('bootstrap_existing_object_differs')
            return copy.deepcopy(ref)
        return self.upload(path, name)

    def read_head(self):
        return copy.deepcopy(self.head), self.generation

    def commit(self, head, generation):
        if generation != self.generation or self.fail_commit:
            raise RuntimeError("precondition failed")
        self.head = copy.deepcopy(head)
        self.generation += 1


@pytest.fixture
def store(tmp_path, master):
    root = tmp_path / "initial"
    root.mkdir()
    shutil.copyfile(master, root / "master.sqlite3")
    export_public(master, root / "public.sqlite3")
    from tatemono_map.cloud.public_db import validate_public
    store = MemoryStore(tmp_path / "objects")
    commit_release(store, root, "20261016T000000Z-000000000000", 0, {"public_counts": validate_public(root / "public.sqlite3"), "proof": []}, "a" * 40)
    return store
