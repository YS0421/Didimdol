"""한국에너지기술연구원(KIER) 채용공고 게시판."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from ..filters import parse_date, parse_range
from ..models import AttachmentLink, PostingRef
from .base import Adapter, first, text_of

ORIGIN = "https://www.kier.re.kr"
MENU = "MENU00459"


class KierAdapter(Adapter):
    code = "kier"

    def list_urls(self, pages: int) -> list[str]:
        return [f"{ORIGIN}/board?menuId={MENU}&pageNum={i + 1}" for i in range(pages)]

    def parse_list(self, html: str, url: str) -> list[PostingRef]:
        doc = self.doc(html)
        refs = []
        for row in doc.xpath("//table[contains(@class,'board')]//tbody/tr"):
            cells = row.xpath("./td")
            a = first(row, ".//a[contains(@href,'/board/view')]")
            if a is None or len(cells) < 4:
                continue
            m = re.search(r"linkId=(\d+)", a.get("href", ""))
            if not m:
                continue
            start, end = parse_range(text_of(cells[2]))
            if end is None:  # 목록 기간 칸이 '-'이면 제목 속 기간을 쓴다 (예: "(2025. 12. 14.-2025. 12. 18.)")
                found = [parse_date(d) for d in re.findall(r"\d{4}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}", text_of(a))]
                found = [d for d in found if d]
                if found:
                    start, end = start or found[0], found[-1]
            refs.append(PostingRef(
                institute=self.code, external_id=m.group(1), title=text_of(a),
                url=f"{ORIGIN}/board/view?linkId={m.group(1)}&menuId={MENU}",
                posted_on=start, apply_start_on=start, apply_end_on=end, status_text=text_of(cells[3]),
            ))
        return refs

    def parse_detail(self, html: str, ref: PostingRef) -> tuple[str, list[AttachmentLink]]:
        doc = self.doc(html)
        body_el = first(doc, "//div[contains(@class,'view-cont') or contains(@class,'board-cont')]")
        atts = []
        for a in doc.xpath("//a[starts-with(@href,'/fileDownload')]"):
            name = re.sub(r"^파일다운로드\s*", "", text_of(a))
            name = re.sub(r"\(\s*[\d.]+\s*[KMG]?B\s*\)\s*$", "", name).strip()
            atts.append(AttachmentLink(name, urljoin(ORIGIN, a.get("href"))))
        return text_of(body_el), atts
