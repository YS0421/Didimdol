"""첨부파일 → 텍스트. PDF(pypdf), HWP 5.x(olefile), HWPX(zip+XML), ZIP(내부 파일 재귀, 1단계).

첨부파일은 외부에서 받은 신뢰할 수 없는 데이터이므로 실행하지 않고 읽기만 하며,
ZIP은 경로 조작·용량 폭탄을 막기 위해 디스크에 풀지 않고 메모리에서 크기 제한을 두고 읽는다.
"""

from __future__ import annotations

import io
import re
import struct
import zipfile
import zlib
from pathlib import PurePosixPath

MAX_ZIP_MEMBERS = 50
MAX_MEMBER_BYTES = 30 * 1024 * 1024
MAX_TOTAL_UNZIPPED = 80 * 1024 * 1024

SUPPORTED = (".pdf", ".hwp", ".hwpx", ".zip", ".txt", ".docx")


def ext_of(name: str) -> str:
    return PurePosixPath(name.lower()).suffix


def extract_text(name: str, data: bytes, _depth: int = 0) -> str:
    ext = ext_of(name)
    if ext == ".pdf":
        return pdf_text(data)
    if ext == ".hwp":
        return hwp5_text(data)
    if ext == ".hwpx":
        return hwpx_text(data)
    if ext == ".zip" and _depth == 0:
        return zip_text(data)
    if ext == ".txt":
        return data.decode("utf-8", errors="replace")
    if ext == ".docx":
        return docx_text(data)
    raise ValueError(f"unsupported:{ext or 'none'}")


def docx_text(data: bytes) -> str:
    from lxml import etree

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        info = zf.getinfo("word/document.xml")
        if info.file_size > MAX_MEMBER_BYTES:
            raise ValueError("too_large")
        root = etree.fromstring(zf.read(info), parser=etree.XMLParser(resolve_entities=False, no_network=True))
    paras = ["".join(t.text or "" for t in p.iter("{*}t")) for p in root.iter("{*}p")]
    return _clean("\n".join(paras))


def _clean(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------- PDF


def pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:  # 선택 의존성
        raise ValueError("pdf_extractor_missing") from e
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as e:
            raise ValueError("encrypted") from e
    return _clean("\n".join((page.extract_text() or "") for page in reader.pages))


# ---------------------------------------------------------------- HWP 5.x

HWPTAG_PARA_TEXT = 67
# 8 WCHAR를 차지하는 제어 문자 (인라인·확장 컨트롤). 나머지(0,10,13,24~31)는 1 WCHAR.
_WIDE_CONTROLS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}


def _para_text(payload: bytes) -> str:
    chars = struct.unpack(f"<{len(payload) // 2}H", payload[: len(payload) // 2 * 2])
    out, i = [], 0
    while i < len(chars):
        c = chars[i]
        if c < 32:
            if c == 9:
                out.append("\t")
            elif c in (10, 13):
                out.append("\n")
            i += 8 if c in _WIDE_CONTROLS else 1
            continue
        out.append(chr(c))
        i += 1
    return "".join(out)


def _records(data: bytes):
    pos = 0
    while pos + 4 <= len(data):
        (header,) = struct.unpack_from("<I", data, pos)
        pos += 4
        tag, size = header & 0x3FF, (header >> 20) & 0xFFF
        if size == 0xFFF:
            (size,) = struct.unpack_from("<I", data, pos)
            pos += 4
        yield tag, data[pos: pos + size]
        pos += size


def hwp5_text(data: bytes) -> str:
    import olefile

    if not olefile.isOleFile(io.BytesIO(data)):
        raise ValueError("not_hwp5")
    with olefile.OleFileIO(io.BytesIO(data)) as ole:
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack_from("<I", header, 36)[0]
        if flags & 0x2:
            raise ValueError("encrypted")
        if flags & 0x4:
            raise ValueError("distribution_doc")  # 배포용 문서: 본문이 암호화됨
        compressed = bool(flags & 0x1)
        sections = sorted(
            (e for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText" and e[1].startswith("Section")),
            key=lambda e: int(e[1][7:] or 0),
        )
        paras = []
        for entry in sections:
            raw = ole.openstream(entry).read()
            body = zlib.decompress(raw, -15) if compressed else raw
            for tag, payload in _records(body):
                if tag == HWPTAG_PARA_TEXT:
                    paras.append(_para_text(payload))
    return _clean("\n".join(paras))


# ---------------------------------------------------------------- HWPX


def hwpx_text(data: bytes) -> str:
    from lxml import etree

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = sorted(
            (n for n in zf.namelist() if re.match(r"Contents/section\d+\.xml$", n)),
            key=lambda n: int(re.search(r"(\d+)", n).group(1)),
        )
        paras = []
        for n in names:
            info = zf.getinfo(n)
            if info.file_size > MAX_MEMBER_BYTES:
                raise ValueError("too_large")
            root = etree.fromstring(zf.read(n), parser=etree.XMLParser(resolve_entities=False, no_network=True))
            for p in root.iter("{*}p"):
                paras.append("".join(t.text or "" for t in p.iter("{*}t")))
    return _clean("\n".join(paras))


# ---------------------------------------------------------------- ZIP


def _member_name(info: zipfile.ZipInfo) -> str:
    """한국어 zip은 UTF-8 플래그 없이 cp949로 저장된 경우가 많다."""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def zip_text(data: bytes) -> str:
    parts, total = [], 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        members = [i for i in zf.infolist() if not i.is_dir()][:MAX_ZIP_MEMBERS]
        for info in members:
            name = _member_name(info)
            if ext_of(name) not in SUPPORTED or ext_of(name) == ".zip":
                continue
            if info.file_size > MAX_MEMBER_BYTES or total + info.file_size > MAX_TOTAL_UNZIPPED:
                parts.append(f"[{name}: 용량 제한으로 건너뜀]")
                continue
            total += info.file_size
            try:
                text = extract_text(name, zf.read(info), _depth=1)
                parts.append(f"[{PurePosixPath(name).name}]\n{text}")
            except Exception as e:  # 내부 파일 하나가 실패해도 나머지는 계속
                parts.append(f"[{PurePosixPath(name).name}: 추출 실패 {e}]")
    return "\n\n".join(parts)
