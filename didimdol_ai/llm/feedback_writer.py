"""주간 피드백 문장 생성 (Claude API).

역할 분담:
- feedback.py(규칙 엔진): 어떤 피드백(칭찬·격려·채찍질)을, 어떤 근거로 줄지 결정
- 여기(LLM): 결정된 내용을 사용자가 고른 코치 톤의 문장으로만 바꿈

생성된 문장은 코드로 검사하고, 통과하지 못하면 규칙 엔진의 기본 템플릿 문장을 쓴다:
- 근거 데이터에 없는 숫자를 쓰면 탈락 (지어낸 수치 방지)
- 다른 사람과 비교하는 표현이면 탈락 (서비스 원칙: 비교 금지)
- 비난·모욕 표현이면 탈락 (직설형이어도 사람을 깎아내리지 않음)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 실제 호출 시점에만 필요 (import가 느린 환경 대비)
    import anthropic

from ..config import axis_names
from ..feedback import CoachTone, FeedbackItem, WeeklyFeedback
from .client import FALLBACK_BETA, model_name

TONE_GUIDE = {
    "praise": "칭찬형: 따뜻하고 다정하게. 잘한 점을 먼저 구체적으로 짚고, 부족한 점은 부드러운 제안으로.",
    "balanced": "균형형: 담백하고 차분하게. 사실을 짚고 다음 행동을 분명히 제안.",
    "direct": "직설형: 짧고 단호하게. 돌려 말하지 않고 해야 할 일을 명확히. 단, 사람을 깎아내리거나 비꼬지 않는다.",
}

SYSTEM_PROMPT = """너는 과학기술분야 출연연 인턴을 준비하는 학부생의 주간 코치다. 서비스 이름은 '디딤돌'이고 원칙은
"합격 점수 대신, 다음에 준비할 한 칸"이다.

입력으로 이번 주에 전할 피드백 항목들이 주어진다. 각 항목의 종류(칭찬·격려·채찍질)와 근거는 이미 정해져 있다.
너는 그것을 지정된 코치 톤의 한국어 문장으로 다시 쓰기만 한다.

반드시 지킬 것:
- 항목마다 1~2문장, 90자 이내. 존댓말(~해요체).
- 근거(facts)에 있는 사실과 숫자만 쓴다. 새로운 숫자·사실·일정을 만들지 않는다.
- 다른 사람, 평균, 상위 몇 %, 다른 지원자와 비교하지 않는다. 비교 대상은 사용자의 목표와 지난주의 사용자뿐이다.
- 합격 가능성을 예측하거나 보장하지 않는다.
- softened=true인 항목은 원래 채찍질이었지만 사용자의 컨디션이 낮아 격려로 바뀐 것이다. 압박하지 말고 부드럽게.
- suggest_split=true면 할 일을 더 작게 나누자는 제안을 포함한다.
- 비난, 비꼼, 모욕, 죄책감을 자극하는 표현을 쓰지 않는다.
- 컨디션·마음 상태를 점수나 숫자로 말하지 않는다 ("컨디션이 1점" 같은 표현 금지).
- context.next_steps는 이번 주 우선순위 참고용이다. 해당 항목과 직접 관련 있을 때만 언급하고, 관련 없는 항목에 끼워 넣지 않는다.
- 이모지나 특수 기호를 쓰지 않는다.
- healing이 true면 healing_text에 숲 힐링 공간에서 잠시 쉬어 가자는 한 문장을 쓴다 (의학적 조언·진단 금지). 아니면 빈 문자열."""

# 타인 비교 표현 ('우선순위'는 비교가 아니므로 제외)
COMPARISON_WORDS = r"다른\s*(사람|학생|지원자|친구)|평균|상위\s*\d|하위\s*\d|남들|또래|경쟁자|등수|(?<!우선)순위"
COMPARISON_WORDS_RE = re.compile(COMPARISON_WORDS)
# 피드백 문장에서는 '%'도 막는다 (리포트의 '목표 달성도 70%'와 달리 문장 속 %는 비교로 읽히기 쉬움)
COMPARISON = re.compile(COMPARISON_WORDS + r"|\d+\s*%")
HARSH = re.compile(r"한심|게으|부끄럽|실망|형편없|무능|핑계|정신\s*차려|그것도\s*못")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
INVISIBLE = re.compile(r"[​-‏⁠﻿]")


def clean(text: str) -> str:
    return INVISIBLE.sub("", text).strip()


@dataclass
class WrittenFeedback:
    kind: str
    reason: str
    text: str
    source: str  # "llm" | "template"
    rejected_reason: Optional[str] = None


def _facts(item: FeedbackItem) -> dict:
    names = axis_names()
    facts = {k: v for k, v in item.evidence.items() if k != "condition"}  # 컨디션 점수는 문장 재료로 주지 않음
    if item.axis:
        facts["axis"] = names.get(item.axis, item.axis)
    return facts


def _allowed_numbers(item: FeedbackItem, extra: dict) -> set[str]:
    blob = json.dumps(_facts(item), ensure_ascii=False) + item.message + json.dumps(extra, ensure_ascii=False)
    return set(NUMBER.findall(blob))


def _with_rounding(nums: set[str]) -> set[str]:
    """3.67 → 3.7, 4.0 → 4 처럼 반올림·정리한 표기도 허용."""
    out = set(nums)
    for n in nums:
        f = float(n)
        out.add(f"{f:.1f}".rstrip("0").rstrip("."))
        out.add(f"{f:.2f}".rstrip("0").rstrip("."))
    return out


def check_text(text: str, allowed_numbers: set[str]) -> Optional[str]:
    """문제가 있으면 탈락 사유, 없으면 None."""
    if not text.strip():
        return "빈 문장"
    if len(text) > 140:
        return "너무 김"
    if COMPARISON.search(text):
        return "타인 비교 표현"
    if HARSH.search(text):
        return "비난 표현"
    if re.search(r"컨디션[^.]{0,6}\d", text):
        return "컨디션 수치 언급"
    allowed = _with_rounding(allowed_numbers)
    for n in NUMBER.findall(text):
        if n not in allowed:
            return f"근거에 없는 숫자 {n}"
    return None


def _schema(n: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "messages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"index": {"type": "integer", "enum": list(range(n))}, "text": {"type": "string"}},
                    "required": ["index", "text"],
                    "additionalProperties": False,
                },
            },
            "healing_text": {"type": "string"},
        },
        "required": ["messages", "healing_text"],
        "additionalProperties": False,
    }


def write_feedback(
    client: anthropic.Anthropic,
    weekly: WeeklyFeedback,
    tone: CoachTone,
    goal_title: str,
    weeks_left: int,
    next_steps: Optional[list[str]] = None,
) -> tuple[list[WrittenFeedback], str]:
    """(피드백 문장 목록, 힐링 제안 문장)을 돌려준다. API 오류 시 예외를 그대로 올린다."""
    items = weekly.items
    healing_default = "이번 주는 숲에서 잠깐 숨을 고르고 와도 괜찮아요." if weekly.suggest_healing else ""
    if not items:
        return [], healing_default

    context = {"goal": goal_title, "weeks_left": weeks_left, "next_steps": next_steps or []}
    payload = {
        "tone": TONE_GUIDE[tone],
        "context": context,
        "healing": weekly.suggest_healing,
        "items": [
            {"index": i, "kind": {"praise": "칭찬", "encourage": "격려", "push": "채찍질"}[it.kind],
             "reason": it.reason, "facts": _facts(it), "default_text": it.message,
             "softened": it.softened, "suggest_split": it.suggest_split}
            for i, it in enumerate(items)
        ],
    }
    response = client.beta.messages.create(
        model=model_name(),
        max_tokens=2000,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        system=SYSTEM_PROMPT,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": _schema(len(items))}},
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=1)}],
    )

    by_index: dict[int, str] = {}
    healing = healing_default
    if response.stop_reason not in ("refusal", "max_tokens"):
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text:
            data = json.loads(text)
            by_index = {m["index"]: clean(m["text"]) for m in data["messages"]}
            h = clean(data.get("healing_text", ""))
            if weekly.suggest_healing and h and not check_text(h, set()):
                healing = h

    out = []
    for i, it in enumerate(items):
        candidate = by_index.get(i, "")
        problem = check_text(candidate, _allowed_numbers(it, context)) if candidate else "응답 없음"
        if problem:
            out.append(WrittenFeedback(it.kind, it.reason, it.message, "template", problem))
        else:
            out.append(WrittenFeedback(it.kind, it.reason, candidate, "llm"))
    return out, healing
