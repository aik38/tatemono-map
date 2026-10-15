from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, PageBreak
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors

from tatemono_map.cli.pdf_batch_run import UlucksParser


def test_table_area_headings_override_office_address_and_continue_across_pages(tmp_path):
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    style = ParagraphStyle("jp", fontName="HeiseiKakuGo-W5", fontSize=12)
    def table(name, room, address):
        t = Table([["物件名", "号室", "所在地", "賃料", "面積"], [name, room, address, "55000", "25.0㎡"]], colWidths=[130,50,180,70,60])
        t.setStyle(TableStyle([("FONTNAME",(0,0),(-1,-1),"HeiseiKakuGo-W5"),("FONTSIZE",(0,0),(-1,-1),10),("GRID",(0,0),(-1,-1),0.5,colors.black)]))
        return t
    p = tmp_path / "synthetic-areas.pdf"
    SimpleDocTemplate(str(p)).build([
        Paragraph("管理会社所在地 北九州市小倉北区架空町", style),
        Paragraph("小倉北区 架空北マンション", style), table("架空北マンション", "101", "魚町1-1-1"),
        Paragraph("小倉南区 架空南マンション", style), table("架空南マンション", "201", "城野2-2-2"),
        PageBreak(), table("架空南マンション", "202", "城野2-2-2"),
    ])
    frame = UlucksParser().parse(p).df
    assert frame["address"].tolist() == ["北九州市小倉北区魚町1-1-1", "北九州市小倉南区城野2-2-2", "北九州市小倉南区城野2-2-2"]
