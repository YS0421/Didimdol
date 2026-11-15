"""공고 직무 추천: 사용자 프로필 + 경험 카드 ↔ 공고에서 추출한 직무(role)·요구 항목.

다른 사용자와 비교하지 않는다. 점수는 '이 사용자의 관심·기록이 이 직무와 얼마나 이어지는가'만 본다.

1) 하드 필터: 학부생 지원 가능, 지원 대상(재학/졸업예정/졸업), 마감 전, 행정 직무 포함 여부, 지역
2) 점수 = w_field·분야 일치 + w_readiness·준비도 + w_style·성향 적합
   - 준비도: 요구 항목별 사용자 근거 수준 / 요구 수준 (가중 평균)
     근거 수준은 Claude 판정 결과가 있으면 그것을, 없으면 카드 텍스트와의 어휘 겹침으로 '추정'한다 (비용 0).
3) 다양성: 같은 공고 최대 2개, 같은 기관 최대 3개 직무
4) 설명: 분야 일치, 내 카드 ↔ 요구 항목 연결, 부족한 항목, 마감일
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional

from . import ncs as ncs_mod
from .config import load_planning
from .models import ExperienceCard, Requirement
from .scoring import is_basic_competency, requirement_weight  # 직업기초능력: 직무 간 차이를 만들지 않아 추천 점수에서 뺌

FIELD_NAMES = {"mech": "기계항공", "elec": "전기전자", "chem": "화학생명", "it": "IT", "ai": "AI데이터",
               "material": "소재재료", "energy": "에너지환경", "infra": "건설인프라"}
CATEGORY_STYLE = {"research": ("analyze", "make"), "admin": ("talk", "plan")}

BUCKET_NOW = "지금 도전할 자리"
BUCKET_PREPARE = "준비하며 목표로 삼을 자리"
BUCKET_LATER = "자격을 갖춘 뒤 목표로 삼을 자리"

KIND_BASE_LEVEL = {"수업": 1, "독학": 1, "자격증": 1, "수업 프로젝트": 2, "동아리": 2, "공모전": 2,
                   "학부연구생": 2, "인턴": 2}
LEAD_PATTERN = re.compile(r"직접\s*설계|스스로|주도|팀장|직접\s*정|기획했|이끌")


@dataclass
class UserProfile:
    status: str  # enrolled / expected / graduated
    interest_fields: list[str]
    regions: list[str] = field(default_factory=list)
    style_share: dict[str, float] = field(default_factory=dict)
    weekly_hours: float = 8
    include_admin: bool = False


@dataclass
class RoleCandidate:
    uid: str
    role_index: int
    posting_title: str
    institute_code: str
    institute_name: str
    region: Optional[str]
    role_name: str
    category: str
    fields: list[str]
    targets: list[str]
    undergrad_eligible: Optional[bool]
    is_closed: bool
    apply_end_on: Optional[str]
    url: str
    ncs: Optional[dict]
    requirements: list[Requirement]
    ncs_codes: list[str] = field(default_factory=list)
    curated_used: bool = False  # 공고에 요구 항목이 없어 NCS 능력단위 기본값을 쓴 경우


@dataclass
class Match:
    requirement: str
    card_id: str
    card_title: str
    level: int
    source: str  # "판정" | "추정"


@dataclass
class Recommendation:
    uid: str
    role_index: int
    title: str
    institute: str
    role_name: str
    score: float
    bucket: str  # "지금 도전할 자리" | "준비하며 목표로 삼을 자리"
    field_fit: float
    readiness: Optional[float]
    style_fit: float
    apply_end_on: Optional[str]
    url: str
    reasons: list[str]
    matches: list[Match]
    gaps: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- 후보 만들기


def candidates_from_store(store, institutes: dict[str, dict]) -> list[RoleCandidate]:
    """수집 DB의 공고 + Claude 추출 결과 → 직무 단위 후보 목록."""
    from .llm.requirements import Extraction  # anthropic 없이도 import 되도록 지연

    out = []
    for p in store.export(institutes):
        ext = store.get_extraction(p["uid"])
        if not ext:
            continue
        e = Extraction(ext["uid"], ext["model"], ext["roles"])
        for i, role in enumerate(e.roles):
            elig = role["eligibility"]
            reqs = e.to_requirements(i)
            codes = ncs_mod.find_detail_codes(role.get("ncs"))
            fields = role["fields"] or ncs_mod.fields_for(codes)
            curated = False
            if codes and not any(r.kind != "attitude" and not r.is_checklist_only for r in reqs):
                for c in codes:  # 능력단위가 있는 첫 세분류로 기본 요구 항목을 채운다 (근거 출처 C)
                    extra = ncs_mod.curated_requirements(c, f"{p['uid']}#{i}")
                    if extra:
                        reqs, curated = reqs + extra, True
                        break
            out.append(RoleCandidate(
                uid=p["uid"], role_index=i, posting_title=p["title"],
                institute_code=p["institute"]["code"], institute_name=p["institute"]["name"],
                region=p.get("region"), role_name=role["role_name"], category=role["category"],
                fields=fields, targets=elig.get("targets", []),
                undergrad_eligible=elig.get("undergrad_eligible"), is_closed=p["is_closed"],
                apply_end_on=p["apply_end_on"], url=p["official_url"], ncs=role.get("ncs"),
                requirements=reqs, ncs_codes=codes, curated_used=curated,
            ))
    return out


# ---------------------------------------------------------------- 근거 추정 (어휘 겹침)


GENERIC = {"일반", "지식", "능력", "경험", "관련", "이해", "기초", "기본", "활용", "업무", "분야", "수행",
           "자의", "있는", "우대", "보유", "가능", "한자", "대한", "위한", "등의"}


def _bigrams(text: str) -> set[str]:
    grams = set()
    for tok in re.findall(r"[0-9A-Za-z가-힣]+", text.lower()):
        if len(tok) == 1:
            continue
        grams.update(tok[i:i + 2] for i in range(len(tok) - 1))
    return grams - GENERIC  # 어느 공고·카드에나 나오는 말은 연결 근거로 쓰지 않음


def _token_grams(text: str) -> list[set[str]]:
    """낱말별 2글자 조각. 낱말 경계를 유지해 '전기영동'+'생화학'이 '전기화학'으로 잘못 합쳐지지 않게 한다."""
    return [g for g in (_bigrams(t) for t in re.findall(r"[0-9A-Za-z가-힣]+", text.lower())) if g]


def _overlap(req_text: str, card_tokens: list[set[str]]) -> float:
    """요구 항목의 2글자 조각 중, 카드의 '같은 낱말' 안에서 찾은 비율. 겹침이 1조각뿐이면 0."""
    req_tokens = _token_grams(req_text)
    total = sum(len(t) for t in req_tokens)
    if not total:
        return 0.0
    hit = sum(max((len(t & c) for c in card_tokens), default=0) for t in req_tokens)
    return hit / total if hit >= 2 else 0.0


def estimate_card_level(card: ExperienceCard) -> int:
    base = KIND_BASE_LEVEL.get(card.kind, 1)
    if base >= 2 and LEAD_PATTERN.search(card.actions + card.role):
        return 3
    return base


def estimate_evidence(req: Requirement, cards: list[ExperienceCard], threshold: float) -> Optional[Match]:
    if req.kind == "attitude":  # "대학원 진학 관심" 같은 태도·의향은 카드 글자 겹침으로 추정하지 않음
        return None
    variants = [t for t in (req.label, req.quote) if t and _bigrams(t)]  # 짧은 항목명이 더 잘 맞는 경우가 많음
    if not variants:
        return None
    best: Optional[Match] = None
    for c in cards:
        card_tokens = _token_grams(c.text())
        overlap = max(_overlap(v, card_tokens) for v in variants)
        if overlap < threshold:
            continue
        level = estimate_card_level(c)
        if best is None or level > best.level:
            best = Match(req.label, c.id, c.title, level, "추정")
    return best


# ---------------------------------------------------------------- 점수


def _field_fit(role: RoleCandidate, profile: UserProfile) -> float:
    if not role.fields:
        return 0.5
    return 1.0 if set(role.fields) & set(profile.interest_fields) else 0.0


def _style_fit(role: RoleCandidate, profile: UserProfile) -> float:
    styles = CATEGORY_STYLE.get(role.category)
    if not styles or not profile.style_share:
        return 0.5
    return min(1.0, sum(profile.style_share.get(s, 0.0) for s in styles))


def _passes_filters(role: RoleCandidate, profile: UserProfile, include_closed: bool, today: date) -> bool:
    if role.undergrad_eligible is False:
        return False
    # 지원 대상(재학/졸업예정/졸업)이 지금과 달라도 제외하지 않는다 → '자격을 갖춘 뒤 목표' 로 분류
    if role.is_closed and not include_closed:
        return False
    if not include_closed and role.apply_end_on and role.apply_end_on < today.isoformat():
        return False
    if role.category == "admin" and not profile.include_admin:
        return False
    if profile.regions and role.region and role.region not in profile.regions:
        return False
    return True


def score_role(
    role: RoleCandidate, profile: UserProfile, cards: list[ExperienceCard],
    judged: Optional[dict[str, Match]] = None,
) -> Recommendation:
    cfg = load_planning()["recommend"]
    judged = judged or {}
    field_fit, style_fit = _field_fit(role, profile), _style_fit(role, profile)

    matches, gaps = [], []
    num = den = 0.0
    for req in role.requirements:
        if req.is_checklist_only or req.required_level == 0 or is_basic_competency(req):
            continue
        m = judged.get(req.id) or estimate_evidence(req, cards, cfg["match_threshold"])
        level = m.level if m else 0
        w = requirement_weight(req)
        num += w * min(level, req.required_level) / req.required_level
        den += w
        if m:
            matches.append(m)
        if level < req.required_level and req.kind != "attitude":
            gaps.append(f"{req.label} (수준 {level} → {req.required_level}, "
                        f"{'필수' if req.necessity == 'required' else '우대'})")
    readiness = round(num / den, 3) if den else None

    score = (cfg["w_field"] * field_fit + cfg["w_readiness"] * (readiness if readiness is not None else cfg.get("unknown_readiness", 0.35))
             + cfg["w_style"] * style_fit)
    reasons = []
    hit = [FIELD_NAMES.get(f, f) for f in role.fields if f in profile.interest_fields]
    if hit:
        reasons.append(f"관심 분야({', '.join(hit)})와 이어져요")
    if matches:
        reasons.append(f"내 기록 {len({m.card_id for m in matches})}개가 요구 항목 {len(matches)}개와 연결돼요")
    if role.ncs_codes:
        names = [ncs_mod.load()["details"][c]["name"] for c in role.ncs_codes[:2]]
        reasons.append(f"NCS 직무: {', '.join(names)}")
    if role.curated_used:
        reasons.append("공고에 구체적인 요건이 없어 NCS 능력단위를 기본 요건으로 썼어요")
    if readiness is None:
        reasons.append("공고에 구체적인 직무 요건이 없어 분야·성향으로만 골랐어요")
    if role.apply_end_on:
        reasons.append(f"마감 {role.apply_end_on}")
    eligible_now = not role.targets or profile.status in role.targets
    if not eligible_now:
        target_names = {"enrolled": "재학생", "expected": "졸업예정자", "graduated": "학사 졸업자"}
        reasons.append(f"지원 대상: {', '.join(target_names[t] for t in role.targets)} — 지금은 지원 시기가 아니에요")
        bucket = BUCKET_LATER
    elif (readiness or 0) >= cfg["ready_threshold"]:
        bucket = BUCKET_NOW
    else:
        bucket = BUCKET_PREPARE
    return Recommendation(
        role.uid, role.role_index, role.posting_title, role.institute_name, role.role_name,
        round(score, 3), bucket, field_fit, readiness, round(style_fit, 3), role.apply_end_on, role.url,
        reasons, matches, gaps[:3],
    )


def recommend(
    roles: list[RoleCandidate], profile: UserProfile, cards: list[ExperienceCard],
    top: int = 5, include_closed: bool = False, today: Optional[date] = None,
    judged_by_role: Optional[dict[tuple[str, int], dict[str, Match]]] = None,
) -> list[Recommendation]:
    cfg = load_planning()["recommend"]
    today = today or date.today()
    judged_by_role = judged_by_role or {}
    scored = [
        score_role(r, profile, cards, judged_by_role.get((r.uid, r.role_index)))
        for r in roles if _passes_filters(r, profile, include_closed, today)
    ]
    order = {BUCKET_NOW: 0, BUCKET_PREPARE: 1, BUCKET_LATER: 2}
    scored.sort(key=lambda r: (order[r.bucket], -r.score, -(r.readiness or 0)))
    picked, per_posting, per_inst = [], {}, {}
    for rec in scored:
        inst = rec.institute
        if per_posting.get(rec.uid, 0) >= cfg["max_per_posting"] or per_inst.get(inst, 0) >= cfg["max_per_institute"]:
            continue
        picked.append(rec)
        per_posting[rec.uid] = per_posting.get(rec.uid, 0) + 1
        per_inst[inst] = per_inst.get(inst, 0) + 1
        if len(picked) >= top:
            break
    return picked
