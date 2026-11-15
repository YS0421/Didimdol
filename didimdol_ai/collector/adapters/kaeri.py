"""한국원자력연구원(KAERI) 채용공고 게시판. KIER와 같은 게시판 엔진이지만 목록이 카드(ul) 모양이다."""

from __future__ import annotations

import re

from ..filters import parse_date
from ..models import AttachmentLink, PostingRef
from .base import Adapter, attachment_links, first, longest, text_of

ORIGIN = "https://www.kaeri.re.kr"
MENU = "MENU00428"


class KaeriAdapter(Adapter):
    code = "kaeri"

    def list_urls(self, pages: int) -> list[str]:
        return [f"{ORIGIN}/board?menuId={MENU}&pageNum={i + 1}" for i in range(pages)]

    def parse_list(self, html: str, url: str) -> list[PostingRef]:
        doc = self.doc(html)
        refs = []
        for item in doc.xpath("//ul[contains(@class,'newsfeed_lst')]/li"):
            a = first(item, ".//strong[contains(@class,'subject')]/a")
            m = re.search(r"linkId=(\d+)", a.get("href", "")) if a is not None else None
            if not m:
                continue
            posted = next((d for d in (parse_date(text_of(dd)) for dd in item.xpath(".//dl[contains(@class,'info')]/dd"))
                           if d), None)
            refs.append(PostingRef(
                institute=self.code, external_id=m.group(1), title=text_of(a),
                url=f"{ORIGIN}/board/view?linkId={m.group(1)}&menuId={MENU}",
                posted_on=posted, status_text=text_of(first(item, ".//dd[contains(@class,'receipt')]")),
            ))
        return refs

    def parse_detail(self, html: str, ref: PostingRef) -> tuple[str, list[AttachmentLink]]:
        doc = self.doc(html)
        body = longest(doc, "//div[contains(@class,'board_body')]")
        return text_of(body), attachment_links(doc, "//a[starts-with(@href,'/fileDownload')]", ORIGIN)
