"""한국기계연구원(KIMM) 채용공고 게시판 (정규직 sub050301).

공고문이 PNG 이미지로만 올라오는 경우가 있다. 이미지 첨부는 텍스트 추출 대상이 아니라 건너뛰고,
직무기술서(ZIP 안의 PDF·HWP)에서 요구 항목을 읽는다.
"""

from __future__ import annotations

import re

from ..filters import parse_date
from ..models import AttachmentLink, PostingRef
from .base import Adapter, attachment_links, first, longest, text_of

ORIGIN = "https://www.kimm.re.kr"
BOARD = f"{ORIGIN}/sub050301"


class KimmAdapter(Adapter):
    code = "kimm"

    def list_urls(self, pages: int) -> list[str]:
        return [BOARD] + [f"{BOARD}/index/page/{i + 1}" for i in range(1, pages)]

    def parse_list(self, html: str, url: str) -> list[PostingRef]:
        doc = self.doc(html)
        refs = []
        for row in doc.xpath("//table//tbody/tr"):
            a = first(row, "./td[@aria-label='제목']//a")
            m = re.search(r"/view/id/(\d+)", a.get("href", "")) if a is not None else None
            if not m:
                continue
            refs.append(PostingRef(
                institute=self.code, external_id=m.group(1), title=text_of(a), url=f"{BOARD}/view/id/{m.group(1)}",
                apply_end_on=parse_date(text_of(first(row, "./td[@aria-label='접수마감일']"))),
                status_text=text_of(first(row, "./td[@aria-label='상태']")),
            ))
        return refs

    def parse_detail(self, html: str, ref: PostingRef) -> tuple[str, list[AttachmentLink]]:
        doc = self.doc(html)
        body = longest(doc, "//div[contains(@class,'board_view')]")
        return text_of(body), attachment_links(doc, "//a[contains(@href,'/file_down/')]", ORIGIN)
