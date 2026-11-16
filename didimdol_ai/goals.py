"""목표선용 요구 항목.

공고를 수단으로 고정하면 그 직무의 요구 항목을 그대로 쓴다 (api._role).
고정하지 않으면 고른 분야의 공통 요구를 만든다.
- 빈도는 추천과 같은 공고만 센다. 마감·대학원생 전용·행정 직무는 빼 둔다.
- 항목 id는 분야 조합과 무관하다. 같은 항목은 분야를 바꿔도 같은 id를 유지한다.
- NCS 보충은 그 분야 공고의 세분류, 또는 목표 문장과 가까운 세분류에서만 가져온다.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date

from .models import Requirement
from .ncs import load as load_ncs
from .recommend import RoleCandidate, UserProfile, _passes_filters
from .scoring import is_basic_competency

POSTING_CAP = 12
NCS_CAP = 8
NCS_WHEN_FEWER_THAN = 4

# 목표 문장에서 직무를 가릴 때 빼는 말. '설계'처럼 세분류 이름에 흔하면 엉뚱한 직무가 이긴다.
_TITLE_STOP = {
    "직접", "스스로", "있게", "되기", "하기", "위한", "통해", "나는", "내가", "우리", "목표", "인턴", "준비",
    "설계", "관리", "개발", "운영", "분석", "계획", "품질", "생산", "기초", "작업", "공정",
}
# 대분류 전체에서 이름만 겹치던 일반 관리 업무. 분야 목표선에 넣지 않는다.
_GENERIC_UNITS = {
    "안전관리", "품질관리", "생산관리", "위생관리", "기초위생관리", "기초안전관리", "재고관리", "부적합품관리",
}


def _norm_label(label: str) -> str:
    return re.sub(r"[\s·‧ㆍ・∙,./()（）]", "", label).lower()


def _median_int(levels: list[int]) -> int:
    ordered = sorted(levels)
    return ordered[(len(ordered) - 1) // 2]


def _mode(items: list):
    if not items:
        return None
    return Counter(items).most_common(1)[0][0]


_PARTICLES = ("으로", "에서", "까지", "부터", "하기", "되기", "있는", "을", "를", "이", "가", "은", "는", "과", "와", "도", "만", "로", "에")


def _stem(word: str) -> str:
    for particle in _PARTICLES:  # 긴 조사부터 위에 둔다
        if word.endswith(particle) and len(word) - len(particle) >= 2:
            return word[: -len(particle)]
    return word


def _title_tokens(title: str) -> list[str]:
    out = []
    for word in re.findall(r"[가-힣A-Za-z]{2,}", title or ""):
        word = _stem(word)
        if word in _TITLE_STOP or word in out:
            continue
        out.append(word)
    return out


def _eligible(roles: list[RoleCandidate], fields: set[str], include_admin: bool, include_closed: bool,
              regions: list[str] | None) -> list[RoleCandidate]:
    """추천 목록과 같은 조건의 직무만 빈도에 넣는다."""
    profile = UserProfile("enrolled", [], regions or [], include_admin=include_admin)
    today = date.today()
    return [r for r in roles
            if set(r.fields) & fields and _passes_filters(r, profile, include_closed, today)]


def _posting_requirements(roles: list[RoleCandidate]) -> list[Requirement]:
    if not roles:
        return []
    buckets: dict[str, dict] = {}
    for role in roles:
        seen: set[str] = set()
        for req in role.requirements:
            if req.required_level <= 0 or is_basic_competency(req):
                continue
            key = _norm_label(req.label)
            if not key or key in seen:
                continue
            seen.add(key)
            bucket = buckets.setdefault(key, {"label": req.label, "levels": [], "axes": [], "kinds": [], "quotes": []})
            bucket["levels"].append(req.required_level)
            bucket["axes"].append(tuple(req.axes))
            if req.kind:
                bucket["kinds"].append(req.kind)
            if req.quote:
                bucket["quotes"].append(req.quote)
    n = len(roles)
    ranked = sorted(buckets.items(), key=lambda kv: (-len(kv[1]["levels"]), kv[1]["label"]))
    out = []
    for key, bucket in ranked[:POSTING_CAP]:
        axes = _mode([a for a in bucket["axes"] if a]) or ()
        frequency = round(len(bucket["levels"]) / n, 3)
        out.append(Requirement(
            id=f"req#{key}",
            label=bucket["label"],
            required_level=max(1, min(3, _median_int(bucket["levels"]))),
            axes=list(axes),
            source="posting",
            necessity="required" if frequency >= 0.5 else "preferred",
            quote=bucket["quotes"][0] if bucket["quotes"] else "",
            frequency=frequency,
            kind=_mode(bucket["kinds"]),
        ))
    return out


def _detail_score(detail: dict, tokens: list[str]) -> int:
    if not tokens:
        return 0
    name = detail["name"]
    units = [u["name"] for u in detail.get("units") or []]
    score = 0
    for token in tokens:
        if token in name:
            score += 5
        if any(token in unit for unit in units):
            score += 2
    return score


def _best_detail(fields: set[str], title: str) -> dict | None:
    tokens = _title_tokens(title)
    best, best_score = None, 0
    for detail in load_ncs()["details"].values():
        if not (set(detail.get("fields") or []) & fields):
            continue
        score = _detail_score(detail, tokens)
        if score > best_score:
            best, best_score = detail, score
    return best


def _details_for(fields: set[str], roles: list[RoleCandidate], title: str) -> list[dict]:
    catalog = load_ncs()["details"]
    picked, seen = [], set()
    for role in roles:
        for code in role.ncs_codes:
            detail = catalog.get(code)
            if not detail or code in seen or not (set(detail.get("fields") or []) & fields):
                continue
            seen.add(code)
            picked.append(detail)
    best = _best_detail(fields, title)
    if best and best.get("name") not in {d["name"] for d in picked}:
        # 같은 코드가 아니면 목표 문장에 가까운 세분류를 뒤에 붙인다.
        code = next((c for c, d in catalog.items() if d is best), None)
        if code not in seen:
            picked.append(best)
    return picked


def _ncs_requirements(details: list[dict], tokens: list[str], skip: set[str], limit: int) -> list[Requirement]:
    if limit <= 0 or not details:
        return []
    ranked = sorted(details, key=lambda d: -_detail_score(d, tokens)) if tokens else list(details)
    out = []
    seen_ids: set[str] = set()
    for detail in ranked:
        units = list(detail.get("units") or [])
        if tokens:
            units.sort(key=lambda u: (0 if any(t in u["name"] for t in tokens) else 1, u["code"]))
        for unit in units:
            key = _norm_label(unit["name"])
            if not key or key in skip or key in _GENERIC_UNITS:
                continue
            uid = f"ncs#{unit['code']}"
            if uid in seen_ids:
                continue
            seen_ids.add(uid)
            out.append(Requirement(
                id=uid,
                label=unit["name"],
                required_level=1,
                axes=[unit["axis"]],
                source="ncs_curated",
                necessity="curated",
                quote=f"NCS {detail['name']} 능력단위 {unit['code']}",
                ncs_unit_code=unit["code"],
                kind="knowledge",
            ))
            skip.add(key)
            if len(out) >= limit:
                return out
    return out


def field_requirements(
    fields: list[str],
    roles: list[RoleCandidate] | None = None,
    title: str = "",
    *,
    include_admin: bool = False,
    include_closed: bool = False,
    regions: list[str] | None = None,
) -> list[Requirement]:
    """고른 분야의 공통 요구. 공고 빈도가 먼저이고, 가까운 세분류의 능력단위로 보충한다."""
    fields_set = {f for f in fields if f}
    if not fields_set:
        return []
    eligible = _eligible(roles or [], fields_set, include_admin, include_closed, regions)
    posting = _posting_requirements(eligible)
    skip = {_norm_label(r.label) for r in posting}
    ncs_limit = NCS_CAP if len(posting) < NCS_WHEN_FEWER_THAN else 0
    details = _details_for(fields_set, eligible, title) if ncs_limit else []
    return posting + _ncs_requirements(details, _title_tokens(title), skip, ncs_limit)
