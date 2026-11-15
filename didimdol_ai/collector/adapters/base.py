"""기관 게시판 어댑터 공통 인터페이스. 게시판 구조가 기관마다 달라 기관당 어댑터 1개."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

import lxml.html

from ..models import AttachmentLink, PostingRef


def text_of(el) -> str:
    return re.sub(r"\s+", " ", el.text_content()).strip() if el is not None else ""


def first(doc, xpath: str):
    found = doc.xpath(xpath)
    return found[0] if found else None


def longest(doc, xpath: str):
    """같은 class가 여러 요소에 붙어 있을 때 글이 가장 긴 요소(본문)를 고른다."""
    found = doc.xpath(xpath)
    return max(found, key=lambda e: len(e.text_content())) if found else None


FILE_NAME = re.compile(r"[^\n/\\|]*?\.(?:pdf|hwpx?|docx?|zip|xlsx?|pptx?|png|jpe?g|txt)\b", re.I)


def _file_name(a) -> str:
    """첨부 링크의 파일명: 링크 글자 → download/title 속성 → 가까운 상위 요소 글자 순으로 확장자가 있는 이름을 찾는다."""
    for cand in (text_of(a), a.get("download") or "", a.get("title") or ""):
        m = FILE_NAME.search(cand)
        if m:
            return m.group(0).strip()
    el = a.getparent()
    for _ in range(3):
        if el is None:
            break
        m = FILE_NAME.search(text_of(el))
        if m:
            return m.group(0).strip()
        el = el.getparent()
    return ""


def attachment_links(doc, xpath: str, origin: str) -> list[AttachmentLink]:
    """같은 파일을 가리키는 링크(파일명 링크 + '다운로드' 버튼)를 하나로 합친다."""
    from urllib.parse import urljoin

    seen: dict[str, AttachmentLink] = {}
    for a in doc.xpath(xpath):
        url = urljoin(origin, a.get("href"))
        name = _file_name(a)
        if url not in seen:
            seen[url] = AttachmentLink(name or url.rsplit("/", 1)[-1], url)
        elif name and not FILE_NAME.search(seen[url].name):
            seen[url].name = name
    return list(seen.values())


class Adapter(ABC):
    code: str

    @abstractmethod
    def list_urls(self, pages: int) -> list[str]: ...

    @abstractmethod
    def parse_list(self, html: str, url: str) -> list[PostingRef]: ...

    @abstractmethod
    def parse_detail(self, html: str, ref: PostingRef) -> tuple[str, list[AttachmentLink]]:
        """(본문 텍스트, 첨부 링크 목록)"""

    @staticmethod
    def doc(html: str):
        return lxml.html.fromstring(html)
