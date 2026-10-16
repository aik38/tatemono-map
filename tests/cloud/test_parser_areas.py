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
