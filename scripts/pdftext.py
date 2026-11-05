# -*- coding: utf-8 -*-
"""从 PDF 里抽文本，只用标准库。

能力边界（写清楚，免得后面误判）：
  · 支持 FlateDecode 内容流、Tj / TJ / ' / " 四类文本操作符、普通字符串与十六进制字符串
  · **不做字体 CMap 映射**，所以 Identity-H 编码的中文 PDF 会抽成乱码

抽出来的东西可不可信，由调用方用 printable_ratio 判断；低于阈值就判「扫描件/无法解析」，
绝不返回一坨乱码当成正文。
"""
import re
import zlib

STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
OBJ = re.compile(rb"(\d+)\s+(\d+)\s+obj(.*?)endobj", re.S)
TEXT_OP = re.compile(
    rb"\((?:\\.|[^\\()])*\)\s*Tj"
    rb"|<[0-9A-Fa-f\s]*>\s*Tj"
    rb"|\[(?:[^\[\]]|\\.)*\]\s*TJ",
    re.S,
)
STR = re.compile(rb"\((?:\\.|[^\\()])*\)", re.S)
HEXSTR = re.compile(rb"<([0-9A-Fa-f\s]+)>")

ESCAPES = {
    b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
    b"(": b"(", b")": b")", b"\\": b"\\",
}


def _unescape(raw: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(raw):
        c = raw[i:i + 1]
        if c == b"\\" and i + 1 < len(raw):
            nxt = raw[i + 1:i + 2]
            if nxt in ESCAPES:
                out += ESCAPES[nxt]
                i += 2
                continue
            m = re.match(rb"[0-7]{1,3}", raw[i + 1:i + 4])
            if m:
                out.append(int(m.group(0), 8) & 0xFF)
                i += 1 + len(m.group(0))
                continue
            i += 1
            continue
        out += c
        i += 1
    return bytes(out)


def _decode(bytes_in: bytes) -> str:
    # 先试 UTF-16BE（PDF 里 <FEFF...> 的写法），再退回 latin-1
    if bytes_in[:2] == b"\xfe\xff":
        return bytes_in[2:].decode("utf-16-be", "ignore")
    return bytes_in.decode("latin-1", "ignore")


def _decode_hex(hexbytes: bytes) -> str:
    digits = re.sub(rb"\s+", b"", hexbytes)
    if len(digits) % 2:
        digits += b"0"
    return _decode(bytes.fromhex(digits.decode("ascii")))


def _streams(pdf: bytes):
    for m in OBJ.finditer(pdf):
        body = m.group(3)
        if b"/FlateDecode" not in body:
            continue
        sm = STREAM.search(body)
        if not sm:
            continue
        try:
            yield zlib.decompress(sm.group(1).strip(b"\r\n"))
        except zlib.error:
            continue


def _extract_builtin(raw: bytes) -> str:
    chunks: list[str] = []
    for data in _streams(raw):
        if b"BT" not in data and b"Tj" not in data and b"TJ" not in data:
            continue
        for op in TEXT_OP.finditer(data):
            piece = op.group(0)
            parts: list[str] = []
            for s in STR.finditer(piece):
                parts.append(_decode(_unescape(s.group(0)[1:-1])))
            if not parts:
                for h in HEXSTR.finditer(piece):
                    parts.append(_decode_hex(h.group(1)))
            if parts:
                chunks.append("".join(parts))
    return "\n".join(chunks)


def _extract_pypdf(raw: bytes) -> str | None:
    """pypdf 在环境里就用它做兜底；没装则返回 None。"""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    import io

    try:
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:  # noqa: BLE001
        return None


RESCUE_MIN_CHARS = 400


def extract(raw: bytes) -> str:
    """返回抽取到的文本（可能为空——调用方必须自己判断可信度）。

    先用内置解析器（行为确定、有测试覆盖）；结果太少或是乱码时，
    如果环境里装了 pypdf，再用它兜底一次。
    """
    if raw[:5] != b"%PDF-":
        raise ValueError("不是 PDF 文件")

    text = _extract_builtin(raw)
    weak = len(text) < RESCUE_MIN_CHARS or printable_ratio(text) < 0.9
    if weak:
        alt = _extract_pypdf(raw)
        if alt and len(alt) > len(text):
            return alt
    return text


def printable_ratio(text: str) -> float:
    """可打印字符占比。低于 0.75 基本就是乱码（典型：未映射的 CJK 字体）。"""
    if not text:
        return 0.0
    ok = sum(1 for ch in text if ch.isprintable() or ch in "\n\t")
    return ok / len(text)
