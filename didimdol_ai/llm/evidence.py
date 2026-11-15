"""경험 카드 → 목표 요구 항목별 근거 수준 판정 (Claude API, structured outputs).

LLM은 '이 카드가 어떤 요구 항목을 어느 수준으로 뒷받침하는가'만 판정하고, 결과는 코드로 검증한다:
- requirement_id는 스키마 enum으로 목표의 요구 항목 안에서만 고르게 한다.
- 근거 인용(quote)이 카드 본문에 실제로 있어야 한다. 없으면 그 근거는 버린다.
- 개인정보(이메일·전화번호)는 보내기 전에 가린다.
점수 계산(축 점수·갭·우선순위)은 scoring.py가 코드로 한다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 실제 호출 시점에만 필요 (import가 느린 환경 대비)
    import anthropic

from ..models import Evidence, ExperienceCard, Requirement
from .client import FALLBACK_BETA, model_name
from .requirements import ExtractionError, quote_in_source

SYSTEM_PROMPT = """너는 학부생의 경험 기록이 연구기관 인턴 직무의 요구 항목을 어느 수준까지 뒷받침하는지 판정하는 평가자다.
다른 사람과 비교하지 않는다. 오직 이 카드에 적힌 사실만 본다.

근거 수준:
1 = 접함: 수업·강의·책으로 배움, 원리를 앎
2 = 수행: 주어진 절차·과제를 직접 해 봄 (남이 정한 프로토콜대로 실험, 지시받은 분석 등)
3 = 주도: 스스로 설계·판단해 결과를 냄 (조건·방법을 직접 정함, 분석 방법을 골라 결론을 냄, 팀을 이끎)

규칙:
- 카드에 근거가 있는 요구 항목만 evidence에 넣는다. 근거가 없으면 넣지 않는다.
- 애매하면 낮은 수준을 고른다. 쓰지 않은 내용을 추측하지 않는다.
- 같은 활동이 직접적으로 해당할 때만 인정한다. 비슷한 분야라는 이유만으로 인정하지 않는다.
- quote는 카드 본문에서 근거가 되는 구절을 **그대로 복사**한다 (5~60자, 바꾸거나 요약하지 않음).
- reason은 왜 그 수준인지 한 문장으로 쓴다.
- 카드가 너무 짧아 판단하기 어렵다면 followup_questions에 사용자에게 물어볼 질문을 최대 2개 쓴다
  (예: "결과는 어떻게 확인했나요?", "실험 조건은 누가 정했나요?"). 충분하면 빈 배열."""

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\b0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}\b")


def mask_pii(text: str) -> str:
    return _PHONE.sub("[전화번호]", _EMAIL.sub("[이메일]", text))


def _schema(requirement_ids: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "requirement_id": {"type": "string", "enum": requirement_ids},
                        "level": {"type": "integer", "enum": [1, 2, 3]},
                        "quote": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["requirement_id", "level", "quote", "reason"],
                    "additionalProperties": False,
                },
            },
            "followup_questions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["evidence", "followup_questions"],
        "additionalProperties": False,
    }


def _requirements_block(requirements: list[Requirement]) -> str:
    lines = []
    for r in requirements:
        need = {"required": "필수", "preferred": "우대"}.get(r.necessity, "기본")
        lines.append(f"- id={r.id} | {r.label} | {need}, 요구 수준 {r.required_level} | 공고 원문: \"{r.quote}\"")
    return "\n".join(lines)


@dataclass
class CardJudgment:
    card_id: str
    evidences: list[Evidence]
    reasons: dict[str, str]  # requirement_id → 판정 이유
    followup_questions: list[str]
    dropped: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


def verify_judgment(card: ExperienceCard, data: dict, valid_ids: set[str], card_text: str) -> CardJudgment:
    evidences, reasons, dropped = [], {}, []
    best: dict[str, dict] = {}
    for e in data.get("evidence", []):
        if e["requirement_id"] not in valid_ids or not quote_in_source(e["quote"], card_text):
            dropped.append(e)
            continue
        prev = best.get(e["requirement_id"])
        if prev is None or e["level"] > prev["level"]:  # 같은 항목이 여러 번 나오면 가장 높은 근거만
            best[e["requirement_id"]] = e
    for rid, e in best.items():
        evidences.append(Evidence(rid, e["level"], card.id, e["quote"]))
        reasons[rid] = e["reason"]
    return CardJudgment(card.id, evidences, reasons, data.get("followup_questions", [])[:2], dropped)


def judge_card(client: anthropic.Anthropic, card: ExperienceCard, requirements: list[Requirement]) -> CardJudgment:
    if not requirements:
        raise ExtractionError("판정할 요구 항목이 없어요.")
    card_text = mask_pii(card.text())
    ids = [r.id for r in requirements]
    response = client.beta.messages.create(
        model=model_name(),
        max_tokens=8000,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        system=SYSTEM_PROMPT,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _schema(ids)}},
        messages=[{
            "role": "user",
            "content": f"# 목표 직무의 요구 항목\n{_requirements_block(requirements)}\n\n# 경험 카드\n{card_text}",
        }],
    )
    if response.stop_reason == "refusal":
        raise ExtractionError("모델이 처리를 거절했어요.")
    if response.stop_reason == "max_tokens":
        raise ExtractionError("출력이 max_tokens에서 잘렸어요.")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise ExtractionError("응답에 텍스트 블록이 없어요.")
    judgment = verify_judgment(card, json.loads(text), set(ids), card_text)
    judgment.usage = {"input_tokens": response.usage.input_tokens,
                      "output_tokens": response.usage.output_tokens, "served_by": response.model}
    return judgment
