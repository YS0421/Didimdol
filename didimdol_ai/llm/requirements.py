"""공고 원문(본문 + 첨부 텍스트) → 직무별 요구 항목 (Claude API, structured outputs).

LLM은 '추출'만 하고, 결과는 코드로 검증한다:
- 모든 요구 항목의 원문 인용(quote)이 실제 공고 텍스트에 있어야 한다. 없으면 버린다 (환각 방지).
- 축 id, 분야 id, 수준(0~3)은 스키마 enum으로 강제한다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 실제 호출 시점에만 필요 (import가 느린 환경 대비)
    import anthropic

from ..config import axis_ids
from ..models import Requirement
from .client import FALLBACK_BETA, model_name

FIELDS = ["mech", "elec", "chem", "it", "ai", "material", "energy", "infra"]
MAX_INPUT_CHARS = 200_000  # 이보다 길면 잘라내지 않고 오류로 알린다
MIN_CONTENT_CHARS = 200  # 본문+첨부가 이보다 짧으면 분석할 근거가 없음

SYSTEM_PROMPT = """너는 한국 과학기술분야 정부출연연구소의 채용 공고를 분석해, 학부생이 목표로 삼을 수 있는 '요구 항목'을 구조화하는 분석가다.

입력은 한 공고의 제목, 본문, 첨부(공고문·직무기술서) 텍스트다. PDF에서 뽑은 텍스트라 같은 글자가 두 번 겹치거나 줄바꿈이 어색할 수 있다.

해야 할 일:
1. 공고 안의 모집 직무(분야)를 나눈다. 직무기술서가 분야별로 있으면 분야마다 하나의 role로 만든다.
   - fields는 연구 대상 분야 기준으로 고른다 (업무에 쓰는 도구 기준이 아님). 해당 없으면 빈 배열.
     mech=기계·항공, elec=전기·전자, chem=화학·생명·바이오·의약(한의학 포함), it=정보통신·소프트웨어,
     ai=AI·데이터, material=소재·재료, energy=에너지·환경, infra=건설·인프라
   - eligibility는 공고의 '공통사항' 자격요건과 분야별 학력 조건을 **함께** 적용한다. 분야별로 '학력무관'이어도
     공통사항에 '재학 또는 휴학 중이 아닌 자'가 있으면 enrolled는 넣지 않는다.
   - 직무기술서에 NCS 분류체계(대·중·소·세분류)가 적혀 있으면 ncs에 그대로 옮긴다. 'NCS 미개발 직무'이거나 없으면 null.
2. 각 role의 요구 항목을 뽑는다: 필요 지식, 기술, 도구·소프트웨어, 자격증·어학, 직무 태도.
   항목을 나누는 기준 (실행마다 결과가 같도록 반드시 지킨다):
   - 공고의 글머리 한 줄(○, -, ▪, •, 번호)을 요구 항목 하나로 본다.
   - 한 줄에 쉼표로 여러 능력이 나열돼 있어도 같은 종류(kind)면 하나로 둔다.
     종류가 다른 것이 섞여 있을 때만(예: 지식 + 도구) 종류별로 나눈다.
   - 여러 직무에 똑같이 반복되는 공통 문장(예: 공통 직무수행 태도)은 직무마다 그대로 넣는다.
   - 같은 role 안에서 같은 문장을 두 번 넣지 않는다.
   - 직무기술서의 '직업기초능력' 목록(의사소통능력, 문제해결능력, 자기개발능력, 조직이해능력 등)도
     빠짐없이 능력마다 요구 항목 하나로 넣는다 (kind=skill, necessity=required, required_level=1).
   - 국가공무원법 결격사유, 병역, 부정채용 이력, 나이, 근무이력 같은 일반 결격·행정 조건은 요구 항목이 아니다. 뽑지 않는다.
   - 학력·재학 여부 같은 지원 자격은 요구 항목이 아니라 eligibility에 넣는다.
3. necessity: 자격요건·필수·'~한 자'는 required, '우대'는 preferred.
4. required_level (학부 인턴 지원자 기준, 0~3):
   1 = 이해·수강·기초 지식 수준
   2 = 해 본 경험, '가능자', '경험자', '활용 능력'
   3 = 스스로 설계·주도, 논문·특허·프로젝트 책임 수준
   자격증·어학처럼 있거나 없는 항목은 1.
5. axes: 항목이 기르는 역량 축을 고른다 (복수 가능, 해당 없으면 빈 배열). 자격증·어학·안전교육처럼 축에 맞지 않는 항목은 빈 배열.
   domain=전공 지식, research=연구·실험 수행, data=데이터 분석·도구, problem=문제해결, communication=소통·문서화, collaboration=협업·자기관리
6. quote: 근거가 되는 원문 구절을 **원문에서 그대로 복사**한다. 바꾸거나 요약하지 않는다. 10~80자.
7. 공고에 없는 내용은 절대 지어내지 않는다. 근거가 없으면 항목을 만들지 않는다."""


def _schema() -> dict[str, Any]:
    requirement = {
        "type": "object",
        "properties": {
            "label": {"type": "string", "description": "짧은 항목명 (예: Python 데이터 분석)"},
            "kind": {"type": "string", "enum": ["knowledge", "skill", "tool", "certificate", "attitude"]},
            "necessity": {"type": "string", "enum": ["required", "preferred"]},
            "required_level": {"type": "integer", "enum": [0, 1, 2, 3]},
            "axes": {"type": "array", "items": {"type": "string", "enum": axis_ids()}},
            "quote": {"type": "string"},
        },
        "required": ["label", "kind", "necessity", "required_level", "axes", "quote"],
        "additionalProperties": False,
    }
    role = {
        "type": "object",
        "properties": {
            "role_name": {"type": "string"},
            "category": {"type": "string", "enum": ["research", "admin", "experience"]},
            "fields": {"type": "array", "items": {"type": "string", "enum": FIELDS}},
            "duties": {"type": "array", "items": {"type": "string"}, "description": "수행 업무 요약"},
            "eligibility": {
                "type": "object",
                "properties": {
                    "undergrad_eligible": {
                        "type": "boolean",
                        "description": "학부 재학생·졸업예정자·학사 졸업자가 학사 수준으로 지원할 수 있는 자리면 true. "
                                       "석·박사과정 입학·재학이 조건이거나 석사 이상 학위가 필요하면 false.",
                    },
                    "targets": {"type": "array",
                                "items": {"type": "string", "enum": ["enrolled", "expected", "graduated"]}},
                    "notes": {"type": "string"},
                },
                "required": ["undergrad_eligible", "targets", "notes"],
                "additionalProperties": False,
            },
            "ncs": {
                "anyOf": [
                    {"type": "null"},
                    {
                        "type": "object",
                        "properties": {
                            "major": {"type": "string"}, "middle": {"type": "string"},
                            "minor": {"type": "string"}, "detail": {"type": "string"},
                        },
                        "required": ["major", "middle", "minor", "detail"],
                        "additionalProperties": False,
                    },
                ],
                "description": "직무기술서에 적힌 NCS 대·중·소·세분류",
            },
            "requirements": {"type": "array", "items": requirement},
        },
        "required": ["role_name", "category", "fields", "duties", "eligibility", "ncs", "requirements"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"roles": {"type": "array", "items": role}},
        "required": ["roles"],
        "additionalProperties": False,
    }


# ---------------------------------------------------------------- 입력 구성


def build_document(posting: dict) -> str:
    """export(with_text) 한 건 → LLM 입력 텍스트."""
    parts = [f"# 공고 제목\n{posting['title']}", f"# 기관\n{posting['institute']['name']}"]
    if posting.get("body_text"):
        parts.append(f"# 본문\n{posting['body_text']}")
    for a in posting.get("attachments", []):
        if a.get("text"):
            parts.append(f"# 첨부: {a['name']}\n{a['text']}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------- 인용 검증


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _dedouble(s: str) -> str:
    """PDF에서 '자격요건자격요건'처럼 겹친 구간을 한 번으로 줄인 버전."""
    return re.sub(r"(.{2,40}?)\1", r"\1", s)


def quote_in_source(quote: str, source: str) -> bool:
    q = _norm(quote)
    if len(q) < 3:
        return False
    src = _norm(source)
    return q in src or _dedouble(q) in _dedouble(src) or q in _dedouble(src)


# ---------------------------------------------------------------- 결과


@dataclass
class Extraction:
    uid: str
    model: str
    roles: list[dict]
    dropped: list[dict] = field(default_factory=list)  # 인용 검증 실패로 버린 항목
    usage: dict = field(default_factory=dict)

    def to_requirements(self, role_index: int = 0) -> list[Requirement]:
        """한 직무의 요구 항목을 점수 계산용 Requirement로 변환."""
        role = self.roles[role_index]
        return [
            Requirement(
                id=f"{self.uid}#{role_index}-{i}",
                label=r["label"],
                required_level=r["required_level"],
                axes=r["axes"],
                source="posting",
                necessity=r["necessity"],
                quote=r["quote"],
                kind=r.get("kind"),
            )
            for i, r in enumerate(role["requirements"])
        ]

    def to_json(self) -> str:
        return json.dumps(
            {"uid": self.uid, "model": self.model, "roles": self.roles,
             "dropped": self.dropped, "usage": self.usage},
            ensure_ascii=False,
        )


class ExtractionError(Exception):
    pass


class SkipExtraction(ExtractionError):
    """분석할 원문이 없어 API를 호출하지 않고 건너뜀 (실패 아님)."""


NOT_ENROLLED = re.compile(r"재학(또는|및|·|,)?휴학중이아닌|재학중이아닌|재학생(은|은지원)?(불가|제외)")


def apply_eligibility_rules(roles: list[dict], source: str) -> list[dict]:
    """공고 공통 자격을 모든 직무에 코드로 적용한다 (LLM 판정이 직무마다 흔들리는 부분)."""
    if not NOT_ENROLLED.search(_norm(source)):
        return roles
    out = []
    for role in roles:
        elig = role["eligibility"]
        if "enrolled" in elig["targets"]:
            elig = {**elig, "targets": [t for t in elig["targets"] if t != "enrolled"],
                    "notes": (elig["notes"] + " [규칙 보정: 공통사항상 재학·휴학생 지원 불가]").strip()}
        out.append({**role, "eligibility": elig})
    return out


def verify(uid: str, model: str, data: dict, source: str, usage: Optional[dict] = None) -> Extraction:
    roles, dropped = [], []
    for role in data.get("roles", []):
        kept = []
        for req in role["requirements"]:
            (kept if quote_in_source(req["quote"], source) else dropped).append(req)
        roles.append({**role, "requirements": kept})
    return Extraction(uid, model, apply_eligibility_rules(roles, source), dropped, usage or {})


def extract_requirements(client: anthropic.Anthropic, posting: dict) -> Extraction:
    source = build_document(posting)
    content_chars = len(posting.get("body_text") or "") + sum(len(a.get("text") or "") for a in posting.get("attachments", []))
    if content_chars < MIN_CONTENT_CHARS:
        raise SkipExtraction("원문 텍스트가 거의 없어요(첨부를 받지 못한 공고). API를 호출하지 않고 건너뛰어요.")
    if len(source) > MAX_INPUT_CHARS:
        raise ExtractionError(f"입력이 너무 길어요({len(source)}자). 첨부를 나눠 분석해야 해요.")

    model = model_name()
    # 직무가 수십 개인 공고는 출력이 길다 → 스트리밍 + 큰 max_tokens (HTTP 타임아웃 방지)
    with client.beta.messages.stream(
        model=model,
        max_tokens=64000,
        betas=[FALLBACK_BETA],
        fallbacks="default",  # 안전 분류기가 거절하면 서버가 대체 모델로 다시 실행
        system=SYSTEM_PROMPT,
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": _schema()},
        },
        messages=[{"role": "user", "content": source}],
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None) if response.stop_details else None
        raise ExtractionError(f"모델이 처리를 거절했어요 (category={category}).")
    if response.stop_reason == "max_tokens":
        raise ExtractionError("출력이 max_tokens에서 잘렸어요.")

    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise ExtractionError("응답에 텍스트 블록이 없어요.")
    data = json.loads(text)
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "served_by": response.model,
        "request_id": getattr(response, "_request_id", None),
    }
    return verify(posting["uid"], model, data, source, usage)
