"""학사 대상 인턴 공고인지 판정하고, 유형(category)·지원 대상(targets)을 규칙으로 채운다.

규칙 기반 1차 판정이며, 애매한 공고는 이후 AI 요구 항목 추출 단계에서 다시 확인한다.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

from .models import Posting

INCLUDE_TERMS = ["인턴", "학생연구원", "연수생", "체험형", "학부연구생", "현장실습"]
# 제목에 이 말만 있고 INCLUDE_TERMS가 없으면 제외
EXCLUDE_TERMS = ["박사후", "석사후", "경력", "정규직", "전문계약직", "기간제근로자", "위촉", "임원", "원장"]
NOT_POSTING_TERMS = ["안내", "반환", "결과", "합격자", "면접", "취업제한", "변경", "연기"]
CLOSED_STATUS = ["마감", "완료", "종료", "전형완료", "접수마감"]

TARGET_PATTERNS = {
    "enrolled": r"(학부\s*)?재학\s*(생|중|자)?|휴학\s*(생|중)",
    "expected": r"졸업\s*예정|학위\s*취득\s*예정",
    "graduated": r"학사[^\n]{0,15}?(소지|취득|졸업|이상)|대학\s*졸업\s*(자|이상)",
}
# 매칭 뒤 이 범위 안에 부정 표현이 있으면 해당 대상이 아니라는 뜻 ("재학 또는 휴학 중이 아닌 자")
NEGATION = re.compile(r"^[^.\n▪○※]{0,12}?(아닌|불가|제외|안\s*됨|않는)")


def _mentions(pattern: str, text: str) -> bool:
    for m in re.finditer(pattern, text):
        if not NEGATION.search(text[m.end(): m.end() + 20]):
            return True
    return False


# '석박사후연수생'처럼 제외 대상 안에 포함어(연수생)가 들어 있는 말은 포함어 판정 전에 지운다
POSTGRAD_PHRASE = re.compile(r"(?:석\s*[·.]?\s*)?(?:박사후|석사후)\s*(?:연수생|연수연구원|연구원|연수직)?")


def classify(p: Posting) -> None:
    title = p.ref.title
    has_include = [t for t in INCLUDE_TERMS if t in POSTGRAD_PHRASE.sub("", title)]
    has_exclude = [t for t in EXCLUDE_TERMS if t in title]

    if not has_include:
        p.include = False
        if has_exclude:
            p.exclude_reason = f"학사 인턴 아님({', '.join(has_exclude)})"
        elif any(t in title for t in NOT_POSTING_TERMS):
            p.exclude_reason = "채용 공고가 아닌 안내문"
        else:
            p.exclude_reason = "인턴·학생연구원 키워드 없음"
    else:
        p.include = True
        p.exclude_reason = None
        # '결과 발표', '면접 안내' 같은 후속 공지는 인턴 키워드가 있어도 제외
        if re.search(r"(합격자|결과|면접|서류전형)\s*(발표|안내|공지)", title):
            p.include = False
            p.exclude_reason = "전형 결과·일정 공지"

    if "행정" in title:
        p.category = "admin"
    elif "체험형" in title:
        p.category = "experience"
    else:
        p.category = "research"

    text = p.full_text
    p.targets = [k for k, pat in TARGET_PATTERNS.items() if _mentions(pat, text)]


DEADLINE_LABEL = re.compile(r"(?:원서\s*접수|서류\s*접수|지원서?\s*접수|접수\s*기간|모집\s*기간|접수\s*일정|지원\s*기간)")
STALE_DAYS = 60  # 마감일을 끝내 알 수 없을 때, 게시 후 이 기간이 지나면 마감으로 본다


def infer_deadline(text: str) -> tuple[Optional[date], Optional[date]]:
    """목록에 접수기간이 없는 기관: 본문·첨부에서 '접수기간 … ~ …'을 찾아 읽는다."""
    for m in DEADLINE_LABEL.finditer(text):
        window = text[m.end():m.end() + 120]
        line = window.split("\n")[0]
        start, end = parse_range(line if "~" in line else window)
        if end:
            return start, end
    return None, None


def is_closed(p: Posting, today: date) -> bool:
    if any(s in p.ref.status_text for s in CLOSED_STATUS):
        return True
    if p.ref.apply_end_on:
        return p.ref.apply_end_on < today
    posted = p.ref.posted_on or p.ref.apply_start_on
    return bool(posted and (today - posted).days > STALE_DAYS)


def parse_date(s: str) -> Optional[date]:
    """'2026-11-02', '2026/11/02', '26.11.02', '2026.11.02', '2026년 11월 2일' 지원."""
    s = s.strip()
    m = (re.search(r"(\d{2,4})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{1,2})", s)
         or re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", s))
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    if y < 100:
        y += 2000
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def parse_range(s: str) -> tuple[Optional[date], Optional[date]]:
    """'2026-11-02 ~ 2026-11-17', '2026. 10. 2.(금) ~ 10. 16.(금)'(끝 연도 생략) 지원."""
    if "~" not in s:
        return parse_date(s), None
    a, b = s.split("~", 1)
    start, end = parse_date(a), parse_date(b)
    if start and end is None:
        m = re.search(r"(\d{1,2})\s*\.\s*(\d{1,2})", b)
        if m:
            try:
                end = date(start.year, int(m.group(1)), int(m.group(2)))
                if end < start:  # 연말→연초로 넘어가는 경우
                    end = date(start.year + 1, end.month, end.day)
            except ValueError:
                end = None
    return start, end
