"""수집 1회 실행: 목록 → (학사 인턴 후보만) 상세·첨부 → 판정 → 저장 → 실행 기록."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

from ..config import DATA_DIR
from .adapters import ADAPTERS
from .extract import SUPPORTED, ext_of, extract_text
from .filters import classify, infer_deadline, is_closed
from .http import Fetcher, RobotsDisallowed
from .models import Attachment, Posting
from .store import Store

# 지원서·동의서 같은 양식 파일은 요구 항목이 없으므로 받지 않는다
FORM_PATTERN = re.compile(r"양식|서식|반환\s*청구|동의서|지원서|위반\s*사항|검토\s*기준|확인서")


# 열 때마다 바뀌는 숫자(조회수·다운로드 횟수). 본문에 남으면 내용 해시가 매번 달라져 '정정공고'로 오인하고
# 비용이 드는 재분석까지 일어난다.
VOLATILE = re.compile(r"(?:조회\s*수?|다운로드\s*:?|다운로드\s*횟수)\s*[:：]?\s*[\d,]+\s*회?")


def strip_volatile(text: str) -> str:
    return re.sub(r"\s{2,}", " ", VOLATILE.sub("", text)).strip()


def load_institutes() -> dict[str, dict]:
    with open(DATA_DIR / "institutes.json", encoding="utf-8") as f:
        return {i["code"]: i for i in json.load(f)["institutes"]}


def _safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .")[:150] or "file"


@dataclass
class InstituteResult:
    institute: str
    listed: int = 0
    included: int = 0
    new: int = 0
    changed: int = 0
    errors: list[str] = field(default_factory=list)
    alert: Optional[str] = None


def fetch_attachments(fetcher: Fetcher, posting: Posting, links, att_dir: Path) -> list[Attachment]:
    out = []
    for link in links:
        att = Attachment(link.name, link.url)
        if link.url is None:
            att.skipped_reason = "no_direct_url"
        elif FORM_PATTERN.search(link.name):
            att.skipped_reason = "form_template"
        elif ext_of(link.name) not in SUPPORTED:
            att.skipped_reason = f"unsupported:{ext_of(link.name) or 'none'}"
        else:
            target_dir = att_dir / posting.ref.institute / posting.ref.external_id
            target_dir.mkdir(parents=True, exist_ok=True)
            path = target_dir / _safe_name(link.name)
            try:
                fetcher.download(link.url, str(path))
                att.local_path = str(path)
                att.text = extract_text(link.name, path.read_bytes())
            except RobotsDisallowed:
                att.skipped_reason = "robots_disallowed"
            except Exception as e:
                att.skipped_reason = f"error:{e}"[:200]
        out.append(att)
    return out


def collect_institute(
    code: str, fetcher: Fetcher, store: Store, att_dir: Path, pages: int = 1,
    with_attachments: bool = True, today: Optional[date] = None,
    log: Callable[[str], None] = print,
) -> InstituteResult:
    today = today or date.today()
    adapter = ADAPTERS[code]()
    res = InstituteResult(code)
    refs, seen = [], set()
    for url in adapter.list_urls(pages):
        try:
            for ref in adapter.parse_list(fetcher.get_text(url), url):
                if ref.external_id not in seen:  # 고정 공지가 페이지마다 반복됨
                    seen.add(ref.external_id)
                    refs.append(ref)
        except Exception as e:
            res.errors.append(f"list {url}: {e!r}"[:300])
    res.listed = len(refs)

    for ref in refs:
        p = Posting(ref)
        classify(p)  # 제목 기준 1차 판정
        if p.include:
            try:
                body, links = adapter.parse_detail(fetcher.get_text(ref.url), ref)
                p.body_text = strip_volatile(body)
                if with_attachments:
                    p.attachments = fetch_attachments(fetcher, p, links, att_dir)
                else:
                    p.attachments = [Attachment(l.name, l.url, skipped_reason="not_requested") for l in links]
            except Exception as e:
                res.errors.append(f"detail {ref.url}: {e!r}"[:300])
            classify(p)  # 첨부 텍스트까지 보고 지원 대상 재판정
            if ref.apply_end_on is None:  # 목록에 접수기간이 없는 기관은 본문·첨부에서 찾는다
                start, end = infer_deadline(p.full_text)
                if end:
                    ref.apply_start_on, ref.apply_end_on = ref.apply_start_on or start, end
            res.included += int(p.include)
        p.is_closed = is_closed(p, today)
        status = store.upsert(p)
        res.new += status == "new"
        res.changed += status == "changed"
        if p.include:
            log(f"  [{status}] {ref.title} (마감 {ref.apply_end_on}, 대상 {p.targets or '미확인'}, "
                f"첨부 {sum(1 for a in p.attachments if a.text)}/{len(p.attachments)}건 추출)")

    store.log_run(datetime.now().isoformat(timespec="seconds"), code, res.listed,
                  res.included, res.new, res.changed, res.errors)
    if store.recent_zero_runs(code, 2):
        res.alert = "목록이 2회 연속 0건 — 게시판 구조가 바뀌었는지 어댑터를 확인하세요."
    return res
