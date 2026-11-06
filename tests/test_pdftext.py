"""P1 测试：PDF 抽文本 + 归一化清洗。用自造 PDF，不依赖外部文件。"""
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import normalize, pdftext  # noqa: E402

BODY = (
    "BT /F1 11 Tf 60 760 Td (5.2.3 The height of the head restraint shall be)"
    " Tj 0 -14 Td (at least 700 mm above the seat reference point.) Tj ET"
)


def make_pdf(text_ops: str = BODY) -> bytes:
    """造一个结构合法、内容流为 FlateDecode 的最小 PDF。"""
    content = zlib.compress(text_ops.encode("latin-1"))
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>",
        b"<</Length " + str(len(content)).encode() + b"/Filter/FlateDecode>>\nstream\n"
        + content + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objs)+1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<</Size {len(objs)+1}/Root 1 0 R>>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


def test_pdf_extract_text():
    text = pdftext.extract(make_pdf())
    assert "head restraint" in text
    assert "700 mm" in text


def test_pdf_extract_keeps_clause_number():
    assert "5.2.3" in pdftext.extract(make_pdf())


def test_pdf_handles_hex_strings():
    pdf = make_pdf("BT /F1 12 Tf 72 720 Td <48656C6C6F> Tj ET")
    assert "Hello" in pdftext.extract(pdf)


def test_pdf_rejects_non_pdf():
    try:
        pdftext.extract(b"not a pdf at all")
    except ValueError:
        pass
    else:
        raise AssertionError("应当抛 ValueError")


def test_printable_ratio():
    assert pdftext.printable_ratio("hello world") > 0.9
    assert pdftext.printable_ratio("\x00\x01\x02\x03") < 0.1
    assert pdftext.printable_ratio("") == 0.0


def test_scanned_pdf_flagged():
    """文字极少的 PDF 必须判为扫描件，而不是返回空正文。

    注意：不能依赖「环境里没装 pypdf」——CI 会装 pypdf，兜底路径可能抽出更多内容。
    所以这里显式关掉 pypdf 兜底，只验内置解析器这条路径。
    """
    pdf = make_pdf("BT /F1 12 Tf 72 720 Td (a) Tj ET")
    saved = pdftext._extract_pypdf
    pdftext._extract_pypdf = lambda raw: None
    try:
        normalize.from_pdf(pdf)
    except normalize.UnusableDocument as e:
        assert "扫描件" in str(e) or "字符" in str(e)
    else:
        raise AssertionError("应当抛 UnusableDocument")
    finally:
        pdftext._extract_pypdf = saved


def test_pypdf_rescue_does_not_bypass_min_chars():
    """即使装了 pypdf，兜底结果太短也必须判为不可用。"""
    pdf = make_pdf("BT /F1 12 Tf 72 720 Td (a) Tj ET")
    saved = pdftext._extract_pypdf
    pdftext._extract_pypdf = lambda raw: "x" * 10      # 仍然太短
    try:
        normalize.from_pdf(pdf)
    except normalize.UnusableDocument:
        pass
    else:
        raise AssertionError("应当抛 UnusableDocument")
    finally:
        pdftext._extract_pypdf = saved


def test_clean_drops_page_numbers():
    raw = "5.2 Head restraints\n- 12 -\nThe height shall be measured.\n13\n"
    out = normalize.clean(raw)
    assert "12" not in out.split("\n")
    assert "head restraint" in out.lower() or "Head restraints" in out


def test_clean_drops_repeated_headers():
    raw = "\n\n".join(
        f"UNECE R17\n5.2 The height shall be at least {700 + i} mm." for i in range(4)
    )
    out = normalize.clean(raw)
    assert "UNECE R17" not in out
    assert out.count("5.2 The height") == 4


def test_clean_collapses_spaces():
    assert normalize.clean("a    b\t\tc") == "a b c"
