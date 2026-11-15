"""한국식품연구원(KFRI) 채용정보 게시판. 행 전체에 onclick="location.href='/web/board/13/ID'"가 걸려 있다."""

from __future__ import annotations

import re

from ..filters import parse_date
from ..models import AttachmentLink, PostingRef
from .base import Adapter, attachment_links, first, longest, text_of

ORIGIN = "https://www.kfri.re.kr"
BOARD = f"{ORIGIN}/web/board/13"


class KfriAdapter(Adapter):
    code = "kfri"

    def list_urls(self, pages: int) -> list[str]:
        return [f"{BOARD}/postList?page={i + 1}" for i in range(pages)]

    def parse_list(self, html: str, url: str) -> list[PostingRef]:
        doc = self.doc(html)
        refs = []
        for row in doc.xpath("//table//tbody/tr[@onclick]"):
            m = re.search(r"/web/board/13/(\d+)", row.get("onclick", ""))
            title = text_of(first(row, "./td[contains(@class,'tit_td')]"))
            if not m or not title or title.startswith("└"):  # 답글(서류 결과 안내 등)은 공고가 아님
                continue
            dates = [parse_date(text_of(td)) for td in row.xpath("./td")]
            refs.append(PostingRef(
                institute=self.code, external_id=m.group(1), title=re.sub(r"^\[[^\]]*\]\s*", "", title),
                url=f"{BOARD}/{m.group(1)}", posted_on=next((d for d in dates if d), None),
            ))
        return refs

    def parse_detail(self, html: str, ref: PostingRef) -> tuple[str, list[AttachmentLink]]:
        doc = self.doc(html)
        body = longest(doc, "//div[contains(@class,'board-view-box')]")
        return text_of(body), attachment_links(doc, "//a[starts-with(@href,'/upload/attach/')]", ORIGIN)
