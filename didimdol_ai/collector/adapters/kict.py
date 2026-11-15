"""한국건설기술연구원(KICT) 채용공고 게시판.

첨부 다운로드는 JS 함수(egov_download_atchfile)로만 열리고, robots.txt가 /boardDownload.es를
금지하므로 첨부는 이름만 기록하고 받지 않는다.
"""

from __future__ import annotations

import re

from ..filters import parse_range
from ..models import AttachmentLink, PostingRef
from .base import Adapter, first, text_of

BASE = "https://www.kict.re.kr/announcementRecruitWeb"
MID = "a10513030000"


class KictAdapter(Adapter):
    code = "kict"

    def list_urls(self, pages: int) -> list[str]:
        # 게시판 전체가 한 페이지에 나오는 구조라 첫 페이지만 사용
        return [f"{BASE}/getAnnouncementRecruitList.es?mid={MID}"]

    def parse_list(self, html: str, url: str) -> list[PostingRef]:
        doc = self.doc(html)
        refs = []
        for row in doc.xpath("//div[@id='listView']/ul[contains(@class,'notice')]"):
            a = first(row, ".//li[contains(@class,'title')]//a")
            if a is None:
                continue
            m = re.search(r"egov_recruit_detail\([^,]+,\s*'(\d+)'", a.get("onclick") or "")
            if not m:
                continue
            start, end = parse_range(text_of(first(row, ".//li[@aria-title='공고기간']")))
            refs.append(PostingRef(
                institute=self.code,
                external_id=m.group(1),
                title=text_of(a),
                url=f"{BASE}/getAnnouncementRecruitView.es?mid={MID}&id={m.group(1)}",
                posted_on=start, apply_start_on=start, apply_end_on=end,
                status_text=text_of(first(row, ".//span[contains(@class,'state')]")),
            ))
        return refs

    def parse_detail(self, html: str, ref: PostingRef) -> tuple[str, list[AttachmentLink]]:
        doc = self.doc(html)
        body = text_of(first(doc, "//div[contains(@class,'tb_contents')]"))
        names, seen = [], set()
        for a in doc.xpath("//div[contains(@class,'tstyle_view')]//a[contains(@onclick,'egov_download_atchfile')]"):
            m = re.search(r"egov_download_atchfile\('[^']*',\s*'[^']*',\s*'([^']+)'", a.get("onclick") or "")
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                names.append(AttachmentLink(m.group(1), None))
        return body, names
