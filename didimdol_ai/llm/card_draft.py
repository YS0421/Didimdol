"""포트폴리오·이력서 파일 → 경험 카드 초안 (Claude API). 사용자가 확인한 뒤에만 저장한다.

검증:
- 카드마다 원문 근거 구절(source_quote)이 실제 파일 텍스트에 있어야 한다.
- 카드의 '내가 한 행동'이 원문과 어휘가 충분히 겹쳐야 한다 (지어낸 활동 방지).
- 이메일·전화번호는 보내기 전에 가리고, 이름·학교명은 넣지 말라고 지시한다 (블라인드 원칙).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..collector.extract import extract_text
from ..models import ExperienceCard
from ..recommend import _bigrams
from .client import FALLBACK_BETA, model_name
from .evidence import mask_pii
from .requirements import ExtractionError, quote_in_source

if TYPE_CHECKING:
    import anthropic

KINDS = ["수업", "수업 프로젝트", "학부연구생", "공모전", "인턴", "동아리", "독학", "자격증"]
MAX_CHARS = 60_000
MIN_ACTION_OVERLAP = 0.4

SYSTEM_PROMPT = """너는 학부생의 포트폴리오·이력서·자기소개서를 읽고 '경험 카드' 초안으로 나누는 도우미다.

- 경험 하나(수업 프로젝트, 학부연구생, 공모전, 인턴, 동아리 활동, 독학, 자격증 등)마다 카드 하나를 만든다.
- actions(내가 한 행동)는 원문에 적힌 사실만 2~3문장으로 정리한다. 원문에 없는 활동·성과·수치를 만들지 않는다.
- 팀 성과와 개인 역할이 섞여 있으면, 원문에서 확인되는 개인 역할만 쓴다.
- tools에는 원문에 나온 도구·기법·장비만 넣는다.
- 이름, 학교명, 학번, 연락처, 주소 같은 개인 식별 정보는 어느 필드에도 넣지 않는다.
- source_quote는 그 카드의 근거가 되는 원문 구절을 **그대로 복사**한다 (10~80자).
- 원문에 없어서 비어 있는 중요한 정보(역할, 결과, 기간 등)는 questions에 사용자에게 물어볼 질문으로 쓴다 (카드당 최대 2개).
- 원문에 해당 정보가 없으면 그 필드는 빈 문자열로 둔다."""


def _schema() -> dict:
    card = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": KINDS},
            "title": {"type": "string"},
            "period": {"type": "string"},
            "role": {"type": "string"},
            "actions": {"type": "string"},
            "tools": {"type": "array", "items": {"type": "string"}},
            "outcome": {"type": "string"},
            "learned": {"type": "string"},
            "source_quote": {"type": "string"},
            "questions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["kind", "title", "period", "role", "actions", "tools", "outcome", "learned",
                     "source_quote", "questions"],
        "additionalProperties": False,
    }
    return {"type": "object", "properties": {"cards": {"type": "array", "items": card}},
            "required": ["cards"], "additionalProperties": False}


@dataclass
class CardDraft:
    card: ExperienceCard
    source_quote: str
    questions: list[str]


@dataclass
class DraftResult:
    drafts: list[CardDraft]
    rejected: list[dict] = field(default_factory=list)  # (카드, 사유)
    usage: dict = field(default_factory=dict)
    ocr_used: bool = False  # 스캔 PDF·이미지를 Claude OCR로 읽었는지


def verify_drafts(data: dict, source: str, id_prefix: str = "draft") -> DraftResult:
    src_grams = _bigrams(source)
    drafts, rejected = [], []
    for i, c in enumerate(data.get("cards", [])):
        if not quote_in_source(c["source_quote"], source):
            rejected.append({"title": c["title"], "reason": "근거 구절이 원문에 없음"})
            continue
        act = _bigrams(c["actions"])
        overlap = len(act & src_grams) / len(act) if act else 0
        if overlap < MIN_ACTION_OVERLAP:
            rejected.append({"title": c["title"], "reason": f"행동 서술이 원문과 동떨어짐({overlap:.0%})"})
            continue
        card = ExperienceCard(
            id=f"{id_prefix}-{i}", kind=c["kind"], title=c["title"], actions=c["actions"],
            role=c["role"], period=c["period"], outcome=c["outcome"], learned=c["learned"],
            tools=[t for t in c["tools"] if t.lower() in source.lower()],  # 원문에 없는 도구는 뺌
        )
        drafts.append(CardDraft(card, c["source_quote"], c["questions"][:2]))
    return DraftResult(drafts, rejected)


def draft_cards_from_text(client: "anthropic.Anthropic", text: str) -> DraftResult:
    source = mask_pii(text)
    if len(source.strip()) < 50:
        raise ExtractionError("파일에서 읽을 수 있는 글이 거의 없어요 (스캔 이미지 PDF일 수 있어요).")
    if len(source) > MAX_CHARS:
        raise ExtractionError(f"문서가 너무 길어요({len(source):,}자). 경험 부분만 나눠 올려 주세요.")
    response = client.beta.messages.create(
        model=model_name(), max_tokens=8000, betas=[FALLBACK_BETA], fallbacks="default",
        system=SYSTEM_PROMPT,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _schema()}},
        messages=[{"role": "user", "content": source}],
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        raise ExtractionError(f"카드 초안을 만들지 못했어요 ({response.stop_reason}).")
    text_block = next((b.text for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise ExtractionError("응답에 텍스트 블록이 없어요.")
    result = verify_drafts(json.loads(text_block), source)
    result.usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    return result


def draft_cards_from_upload(client: "anthropic.Anthropic", name: str, data: bytes) -> DraftResult:
    """업로드 파일 → 카드 초안. 글이 안 나오는 스캔 PDF·사진은 Claude OCR로 먼저 받아 적는다."""
    from .ocr import needs_ocr, ocr_file

    try:
        text = extract_text(name, data)
    except ValueError:
        text = ""  # 이미지 등 일반 추출 불가 형식
    ocr_usage = {}
    if needs_ocr(name, text):
        ocr = ocr_file(client, name, data)
        if not ocr.legible and len(ocr.text) < 50:
            raise ExtractionError("이미지에서 글자를 거의 읽지 못했어요. 더 선명한 사진이나 원본 파일로 올려 주세요.")
        text, ocr_usage = ocr.text, ocr.usage
    result = draft_cards_from_text(client, text)
    if ocr_usage:
        result.ocr_used = True
        result.usage = {k: result.usage.get(k, 0) + ocr_usage.get(k, 0) for k in ("input_tokens", "output_tokens")}
    return result


def draft_cards_from_file(client: "anthropic.Anthropic", path: str) -> DraftResult:
    p = Path(path)
    return draft_cards_from_upload(client, p.name, p.read_bytes())
