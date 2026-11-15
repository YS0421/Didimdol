"""분석에 쓰는 데이터 구조. jobfit 모듈 테이블과 1:1로 대응시키기 쉽게 단순하게 둔다."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Literal, Optional

Source = Literal["posting", "jd_ncs", "ncs_curated"]
Necessity = Literal["required", "preferred", "curated"]
Style = Literal["analyze", "make", "talk", "plan"]


@dataclass
class Requirement:
    """목표가 요구하는 항목 하나 (공고 추출·직무기술서 NCS·큐레이션 중 하나에서 옴)."""

    id: str
    label: str
    required_level: int  # 0~3 (없음/접함/수행/주도)
    axes: list[str]  # 연결된 6축 id. 공고 고유 요구(자격증·어학 등)는 빈 리스트
    source: Source
    necessity: Necessity = "curated"
    quote: str = ""  # 원문 인용 (목표 근거 표시용)
    ncs_unit_code: Optional[str] = None
    frequency: Optional[float] = None  # 기관·분야 목표일 때 공고 요구 빈도 0~1
    style: Optional[Style] = None  # 이 항목과 잘 맞는 성향
    kind: Optional[str] = None  # knowledge / skill / tool / certificate / attitude (공고 추출 결과)

    @property
    def is_checklist_only(self) -> bool:
        """6축에 연결되지 않는 공고 고유 요구 → 육각형 밖 체크리스트로 표시."""
        return not self.axes


@dataclass
class ExperienceCard:
    """사용자가 기록하는 경험 카드 (가이드형 폼, STAR 경량화)."""

    id: str
    kind: str  # 수업 프로젝트 / 학부연구생 / 공모전 / 인턴 / 동아리 / 독학 / 자격증
    title: str
    actions: str  # 내가 한 행동 (2~3문장)
    role: str = ""
    period: str = ""
    tools: list[str] = field(default_factory=list)
    outcome: str = ""
    learned: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "ExperienceCard":
        """JSON 파일의 카드 → 객체. 예시 데이터의 added_week처럼 카드 필드가 아닌 키는 무시한다."""
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})

    def text(self) -> str:
        """LLM 입력이자 인용 검증 대상이 되는 카드 본문."""
        rows = [
            ("유형", self.kind), ("제목", self.title), ("기간", self.period), ("내 역할", self.role),
            ("내가 한 행동", self.actions), ("도구·기법", ", ".join(self.tools)),
            ("결과·산출물", self.outcome), ("배운 점·다음 질문", self.learned),
        ]
        return "\n".join(f"{k}: {v}" for k, v in rows if v)


@dataclass
class Evidence:
    """경험 카드가 특정 요구 항목을 어느 수준으로 뒷받침하는지 (LLM 판정 결과)."""

    requirement_id: str
    level: int  # 0~3
    card_id: str
    quote: str  # 카드 원문 인용 — 반드시 카드 본문에 실재해야 함


@dataclass
class Goal:
    id: str
    title: str
    requirements: list[Requirement]
    weeks_left: int
    weekly_hours: float


@dataclass
class MilestoneResult:
    milestone_id: str
    title: str
    status: Literal["done", "in_progress", "on_hold"]
    hold_reason: Optional[Literal["external", "time", "unclear", "motivation"]] = None
    consecutive_hold_weeks: int = 0  # 같은 마일스톤이 연속으로 보류된 주 수
    requirement_id: Optional[str] = None  # 이 마일스톤이 메우려는 요구 항목 (행동 템플릿에서 만든 경우)


@dataclass
class Checkin:
    week: str  # ISO 주 (예: "2026-W46")
    self_ratings: dict[str, int]  # axis id → 1~5
    milestones: list[MilestoneResult] = field(default_factory=list)
    hours_spent: Optional[float] = None
    condition: Optional[int] = None  # 1~5, 선택 응답. 진로 점수에는 쓰지 않음
    missed_previous_week: bool = False
