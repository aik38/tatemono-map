from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, PageBreak
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors

from tatemono_map.cli.pdf_batch_run import UlucksParser, write_master_import_csv


def test_table_area_headings_override_office_address_and_continue_across_pages(tmp_path):
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    style = ParagraphStyle("jp", fontName="HeiseiKakuGo-W5", fontSize=12)
    def table(name, room, address):
        t = Table([["物件名", "号室", "所在地", "賃料", "面積"], [name, room, address, "55000", "25.0㎡"]], colWidths=[130,50,180,70,60])
        t.setStyle(TableStyle([("FONTNAME",(0,0),(-1,-1),"HeiseiKakuGo-W5"),("FONTSIZE",(0,0),(-1,-1),10),("GRID",(0,0),(-1,-1),0.5,colors.black)]))
        return t
    p = tmp_path / "synthetic-areas.pdf"
    SimpleDocTemplate(str(p)).build([
        Paragraph("2026年10月16日現在 管理会社所在地 北九州市小倉北区架空町", style),
        Paragraph("小倉北区 架空北マンション", style), table("架空北マンション", "101", "魚町1-1-1"),
        Paragraph("小倉南区 架空南マンション", style), table("架空南マンション", "201", "城野2-2-2"),
        PageBreak(), table("架空南マンション", "202", "城野2-2-2"),
    ])
    frame = UlucksParser().parse(p).df
    assert frame["address"].tolist() == ["北九州市小倉北区魚町1-1-1", "北九州市小倉南区城野2-2-2", "北九州市小倉南区城野2-2-2"]
    assert frame['evidence_id'].is_unique
    assert frame['updated_at'].tolist() == ['2026-10-16'] * 3


def test_pdf_terms_keep_their_meaning_through_master_import(master, config, tmp_path):
    from tatemono_map.cloud.pipeline import update_master
    from tatemono_map.cloud.public_db import readonly
    pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))
    table = Table([
        ['物件名','号室','所在地','賃料','共益費','面積','敷金','礼金'],
        ['架空テストマンション','101','北九州市小倉北区魚町1-1-1','55000','3000','25.0㎡','なし','1ヶ月'],
    ], colWidths=[130,40,210,60,60,50,45,45])
    table.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),'HeiseiKakuGo-W5'),('FONTSIZE',(0,0),(-1,-1),9),('GRID',(0,0),(-1,-1),0.5,colors.black)]))
    pdf = tmp_path/'terms.pdf'
    SimpleDocTemplate(str(pdf),pagesize=(900,400)).build([table])
    result = update_master(master,[pdf],1,config,tmp_path,'terms')
    with readonly(master) as conn:
        assert conn.execute('SELECT deposit_text,key_money_text,rent_yen,maint_yen FROM listings WHERE ingest_run_id=?',(result['ingest_run_id'],)).fetchone() == ('なし','1ヶ月',55000,3000)


def test_county_and_city_headings_replace_previous_ward_and_continue(tmp_path):
    pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))
    style=ParagraphStyle('region',fontName='HeiseiKakuGo-W5',fontSize=12)
    def table(address):
        t=Table([['物件名','号室','所在地','賃料','面積'],['架空広域建物','101',address,'55000','25.0㎡']],colWidths=[130,50,190,60,60])
        t.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),'HeiseiKakuGo-W5'),('GRID',(0,0),(-1,-1),0.5,colors.black)]))
        return t
    p=tmp_path/'synthetic-counties.pdf'
    SimpleDocTemplate(str(p)).build([
        Paragraph('門司区 架空区内建物',style),table('架空町1-1-1'),
        Paragraph('中間市 架空中間建物',style),table('中央1-1-1'),
        Paragraph('京都郡 架空苅田建物',style),table('苅田町大字架空1-1'),
        PageBreak(),table('苅田町大字架空1-1'),
        Paragraph('行橋市 架空行橋建物',style),table('中央1-1-1'),
        Paragraph('築上郡 架空築上建物',style),table('築上町大字架空1-1'),
    ])
    addresses=UlucksParser().parse(p).df['address'].tolist()
    assert addresses==['北九州市門司区架空町1-1-1','中間市中央1-1-1','京都郡苅田町大字架空1-1','京都郡苅田町大字架空1-1','行橋市中央1-1-1','築上郡築上町大字架空1-1']


def test_geographic_prefixes_do_not_invent_a_town_or_retag_an_explicit_city():
    from tatemono_map.ulucks_geography import complement_print_address,municipality_of
    assert complement_print_address('富久町1-1','京都郡')=='富久町1-1'
    assert complement_print_address('苅田町大字架空1-1','門司区')=='京都郡苅田町大字架空1-1'
    assert complement_print_address('福岡市中央区架空町1-1','門司区')=='福岡市中央区架空町1-1'
    assert municipality_of('京都郡富久町1-1') is None
    assert municipality_of('京都郡苅田町大字架空1-1')=='京都郡苅田町'
    assert complement_print_address('宮市町9番3号','行橋市')=='行橋市宮市町9番3号'
    assert complement_print_address('西宮市二丁目1番40号','行橋市')=='行橋市西宮市二丁目1番40号'

def test_explicit_fukuoka_town_completes_its_unique_county_without_previous_ward():
    from tatemono_map.ulucks_geography import complement_print_address,municipality_of
    for raw in ('芦屋町架空町1-2','福岡県芦屋町架空町1-2'):
        actual=complement_print_address(raw,'小倉北区')
        assert actual.endswith('遠賀郡芦屋町架空町1-2')
        assert municipality_of(actual)=='遠賀郡芦屋町'
    assert complement_print_address('北九州市小倉北区魚町1-1-1','遠賀郡')=='北九州市小倉北区魚町1-1-1'
    assert complement_print_address('兵庫県芦屋市架空町1-2','遠賀郡')=='兵庫県芦屋市架空町1-2'


def test_separate_header_and_single_data_row_require_identical_column_geometry(tmp_path):
    from reportlab.platypus import Spacer
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    header = ["物件名", "号室", "所在地", "賃料", "面積"]
    widths = [130, 50, 190, 60, 60]
    def grid(rows, columns):
        t = Table(rows, colWidths=columns)
        t.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,-1), "HeiseiKakuGo-W5"),
            ("GRID", (0,0), (-1,-1), 0.5, colors.black),
        ]))
        return t
    p = tmp_path / "synthetic-separated-header.pdf"
    SimpleDocTemplate(str(p)).build([
        grid([[""] * 5, header], widths), Spacer(1, 10),
        grid([["架空継続建物", "301", "北九州市小倉北区魚町1-1-1", "55000", "25.0㎡"]], widths),
        Spacer(1, 10),
        grid([header], widths), Spacer(1, 10),
        grid([["架空誤配置", "999", "北九州市小倉北区魚町2-2-2", "99000", "30.0㎡"]], [140,40,190,60,60]),
        Spacer(1, 10),
        grid([["架空見出しなし", "998", "北九州市小倉北区魚町3-3-3", "88000", "30.0㎡"]], widths),
    ])
    frame = UlucksParser().parse(p).df
    assert frame["building_name"].tolist() == ["架空継続建物"]
    assert frame["room"].tolist() == ["301"]
    assert frame["rent_man"].tolist() == [5.5]
    assert frame["evidence_id"].is_unique
