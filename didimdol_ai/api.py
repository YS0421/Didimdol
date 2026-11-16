"""디딤돌 AI API 서버 (G7 jobfit 모듈이 호출).

무상태 설계: 사용자 데이터(프로필·카드·체크인 이력)는 G7이 저장하고 요청마다 보낸다.
이 서버가 가진 상태는 공고 수집 DB(collector_data/postings.sqlite3)뿐이다.

인증: 모든 /v1 요청은 헤더 `X-Didimdol-Key`가 .env의 DIDIMDOL_API_KEY와 같아야 한다.
실행: uvicorn didimdol_ai.api:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, model_validator

from .collector.runner import load_institutes
from .collector.store import Store
from .llm.client import load_dotenv
from .models import Checkin, Evidence, ExperienceCard, Goal, MilestoneResult, Requirement

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("DIDIMDOL_DB", ROOT / "collector_data" / "postings.sqlite3"))
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

load_dotenv()
app = FastAPI(title="디딤돌 AI", version="0.1.0",
              description="출연연 인턴 공고 분석·추천과 목표 기반 성장 리포트 (다른 사용자와 비교하지 않음)")


# ---------------------------------------------------------------- 공통


def require_key(x_didimdol_key: Optional[str] = Header(default=None)) -> None:
    expected = os.environ.get("DIDIMDOL_API_KEY", "")
    if not expected:
        if os.environ.get("DIDIMDOL_ALLOW_NO_AUTH") == "1":  # 로컬 개발용
            return
        raise HTTPException(503, "서버에 DIDIMDOL_API_KEY가 설정되지 않았어요.")
    if not x_didimdol_key or not hmac.compare_digest(x_didimdol_key, expected):
        raise HTTPException(401, "인증 키가 올바르지 않아요.")


def store() -> Store:
    if not DB_PATH.exists():
        raise HTTPException(503, "공고 DB가 없어요. 수집기를 먼저 실행해 주세요.")
    return Store(str(DB_PATH))


_client = None


def llm():
    global _client
    if _client is None:
        from .llm.client import make_client
        try:
            _client = make_client()
        except RuntimeError as e:
            raise HTTPException(503, str(e))
    return _client


def llm_errors(fn):
    """LLM 호출 오류를 HTTP 오류로 바꾼다."""
    from .llm.requirements import ExtractionError
    try:
        return fn()
    except ExtractionError as e:
        raise HTTPException(422, str(e))
    except HTTPException:
        raise
    except Exception as e:  # anthropic.APIError 등 (anthropic import를 피하려고 넓게 받음)
        if type(e).__module__.startswith("anthropic"):
            raise HTTPException(502, f"Claude API 오류: {type(e).__name__}")
        raise


# ---------------------------------------------------------------- 요청 스키마


class CardIn(BaseModel):
    id: str
    kind: str
    title: str
    actions: str
    role: str = ""
    period: str = ""
    tools: list[str] = []
    outcome: str = ""
    learned: str = ""

    def to_model(self) -> ExperienceCard:
        return ExperienceCard(**self.model_dump())


class ProfileIn(BaseModel):
    status: Literal["enrolled", "expected", "graduated"]
    interest_fields: list[str] = []
    regions: list[str] = []
    style_share: dict[str, float] = {}
    weekly_hours: float = 8
    include_admin: bool = False


class RecommendIn(BaseModel):
    profile: ProfileIn
    cards: list[CardIn] = []
    top: int = Field(5, ge=1, le=30)
    include_closed: bool = False


class JudgeIn(BaseModel):
    uid: Optional[str] = None
    role_index: int = 0
    fields: list[str] = []
    title: Optional[str] = None
    card: CardIn

    @model_validator(mode="after")
    def need_anchor(self):
        if (self.uid or "").strip() or self.fields:
            return self
        raise ValueError("공고를 고정했거나 분야를 골라 주세요.")


class EvidenceIn(BaseModel):
    requirement_id: str
    level: int = Field(ge=0, le=3)
    card_id: str
    quote: str = ""


class MilestoneIn(BaseModel):
    milestone_id: str
    title: str
    status: Literal["done", "in_progress", "on_hold"]
    hold_reason: Optional[Literal["external", "time", "unclear", "motivation"]] = None
    consecutive_hold_weeks: int = 0
    requirement_id: Optional[str] = None


class CheckinIn(BaseModel):
    week: str
    self_ratings: dict[str, int] = {}
    milestones: list[MilestoneIn] = []
    hours_spent: Optional[float] = None
    condition: Optional[int] = Field(None, ge=1, le=5)
    missed_previous_week: bool = False


class WeekIn(BaseModel):
    checkin: CheckinIn
    evidences: list[EvidenceIn] = []


class MentoringIn(BaseModel):
    week: str
    question: str
    answered: bool
    followed_up: bool = False


class GoalIn(BaseModel):
    """uid가 있으면 그 인턴 직무를 수단으로 고정한 목표. 없으면 title과 fields로 분야 공통 요구를 쓴다."""

    uid: Optional[str] = None
    role_index: int = 0
    title: Optional[str] = None
    fields: list[str] = []
    weeks_left: int = Field(ge=0)
    weekly_hours: float = Field(gt=0)

    @model_validator(mode="after")
    def need_anchor(self):
        if (self.uid or "").strip():
            return self
        if (self.title or "").strip() and self.fields:
            return self
        raise ValueError("목표 문장과 분야가 필요해요. 인턴을 수단으로 고정했다면 공고 번호가 필요해요.")


class MilestoneRef(BaseModel):
    milestone_id: str
    title: str
    requirement_id: Optional[str] = None


class InputFormIn(BaseModel):
    """자기상태표 입력 화면 조각 요청. 사용자 상태는 G7이 보낸다."""

    week: str
    profile: dict = {}
    coach_tone: Literal["praise", "balanced", "direct"] = "balanced"
    goal: Optional[dict] = None  # {title, fields, weeks_left, weekly_hours, uid?, role_index?}
    last_ratings: dict[str, int] = {}
    milestones: list[MilestoneRef] = []  # 지난주에 제안된 할 일 (리포트의 next_actions)
    cards: list[CardIn] = []
    endpoints: dict[str, str] = {}  # {"checkin": "/api/...", "card": ..., "profile": ..., "draft": ...} G7 저장 경로
    start_tab: Literal["checkin", "cards", "profile"] = "profile"
    missed_previous_week: bool = False
    include_closed_goals: bool = False


class ReportIn(BaseModel):
    goal: GoalIn
    history: list[WeekIn] = Field(min_length=1)
    cards: list[CardIn] = []
    style_share: dict[str, float] = {}
    mentoring: list[MentoringIn] = []
    kind: Literal["weekly", "monthly"] = "weekly"
    format: Literal["json", "html", "html_fragment"] = "json"  # html_fragment: 사이트 페이지에 끼워 넣는 조각
    with_feedback: bool = False
    coach_tone: Literal["praise", "balanced", "direct"] = "balanced"


# ---------------------------------------------------------------- 도우미


def _role(uid: str, role_index: int) -> tuple[dict, list[Requirement]]:
    from .llm.requirements import Extraction

    s = store()
    try:
        ext = s.get_extraction(uid)
    finally:
        s.close()
    if not ext:
        raise HTTPException(404, "이 공고의 요구 항목 분석 결과가 없어요.")
    if not 0 <= role_index < len(ext["roles"]):
        raise HTTPException(404, "직무 번호가 범위를 벗어났어요.")
    e = Extraction(ext["uid"], ext["model"], ext["roles"])
    return ext["roles"][role_index], e.to_requirements(role_index)


def _field_roles():
    """공고 DB가 있으면 직무 후보, 없으면 빈 목록. 분야 목표선은 DB 없이도 NCS로 만든다."""
    from .recommend import candidates_from_store

    if not DB_PATH.exists():
        return []
    s = store()
    try:
        return candidates_from_store(s, load_institutes())
    finally:
        s.close()


def resolve_goal(goal: GoalIn) -> Goal:
    """고정한 인턴이 있으면 그 요구 항목, 없으면 분야 공통 요구로 Goal을 만든다."""
    from .goals import field_requirements

    if (goal.uid or "").strip():
        role, reqs = _role(goal.uid, goal.role_index)
        title = (goal.title or "").strip() or role["role_name"]
        means = role["role_name"] if (goal.title or "").strip() else None
        return Goal(goal.uid, title, reqs, goal.weeks_left, goal.weekly_hours, means)
    reqs = field_requirements(goal.fields, _field_roles(), goal.title or "")
    if not reqs:
        raise HTTPException(422, "이 분야의 공통 요구를 만들지 못했어요.")
    return Goal("field:" + ",".join(sorted(goal.fields)), (goal.title or "").strip(), reqs,
                goal.weeks_left, goal.weekly_hours)


def _checkin(c: CheckinIn) -> Checkin:
    return Checkin(c.week, c.self_ratings, [MilestoneResult(**m.model_dump()) for m in c.milestones],
                   c.hours_spent, c.condition, c.missed_previous_week)


# ---------------------------------------------------------------- 엔드포인트


@app.get("/health")
def health() -> dict:
    return {"ok": True, "db": DB_PATH.exists()}


@app.get("/v1/postings", dependencies=[Depends(require_key)])
def postings(include_closed: bool = False) -> list[dict]:
    s = store()
    try:
        items = s.export(load_institutes())
        analyzed = {r["uid"] for r in s.db.execute("SELECT uid FROM extractions").fetchall()}
    finally:
        s.close()
    out = []
    for p in items:
        if p["is_closed"] and not include_closed:
            continue
        out.append({**p, "analyzed": p["uid"] in analyzed})
    return out


@app.get("/v1/postings/{uid}/roles", dependencies=[Depends(require_key)])
def posting_roles(uid: str) -> dict:
    s = store()
    try:
        ext = s.get_extraction(uid)
    finally:
        s.close()
    if not ext:
        raise HTTPException(404, "이 공고의 요구 항목 분석 결과가 없어요.")
    return {"uid": uid, "roles": ext["roles"]}


@app.get("/v1/ncs/search", dependencies=[Depends(require_key)])
def ncs_search(q: str, limit: int = 20) -> dict:
    from . import ncs

    if len(q.strip()) < 2:
        raise HTTPException(422, "검색어는 2글자 이상이어야 해요.")
    return {"source": ncs.load()["source"], "items": ncs.search(q, min(limit, 50))}


@app.get("/v1/ncs/{code}", dependencies=[Depends(require_key)])
def ncs_detail(code: str) -> dict:
    from . import ncs

    d = ncs.load()["details"].get(code)
    if not d:
        raise HTTPException(404, "큐레이션 범위에 없는 NCS 세분류 코드예요.")
    return {"code": code, **d}


@app.post("/v1/forms/self-status", dependencies=[Depends(require_key)])
def self_status_form(body: InputFormIn) -> HTMLResponse:
    """자기상태표 입력 화면 조각. 관련 인턴은 고른 분야가 있을 때만 추천하고, 고정은 선택이다."""
    from datetime import date

    from .input_html import build_config, render_input_fragment
    from .recommend import UserProfile, _passes_filters, recommend

    fields = (body.profile or {}).get("interest_fields") or []
    options = []
    if fields and DB_PATH.exists():
        profile = UserProfile(
            status=(body.profile or {}).get("status") or "enrolled",
            interest_fields=fields,
            regions=(body.profile or {}).get("regions") or [],
            style_share=(body.profile or {}).get("style_share") or {},
            weekly_hours=(body.profile or {}).get("weekly_hours") or 8,
            include_admin=bool((body.profile or {}).get("include_admin")),
        )
        roles = [r for r in _field_roles() if set(r.fields) & set(fields)]
        recs = recommend(roles, profile, [c.to_model() for c in body.cards],
                         top=5, include_closed=body.include_closed_goals)
        options = [{"uid": r.uid, "role_index": r.role_index, "label": f"{r.institute} · {r.role_name}"} for r in recs]
        pinned = body.goal or {}
        pin_index = int(pinned.get("role_index") or 0)
        if pinned.get("uid") and not any(o["uid"] == pinned["uid"] and o["role_index"] == pin_index for o in options):
            cand = next((r for r in roles if r.uid == pinned["uid"] and r.role_index == pin_index), None)
            # 지금 분야에 맞고 추천과 같은 조건일 때만 고정을 유지한다. 다른 분야 공고는 다시 넣지 않는다.
            if (cand and set(cand.fields) & set(fields)
                    and _passes_filters(cand, profile, body.include_closed_goals, date.today())):
                options.insert(0, {"uid": cand.uid, "role_index": cand.role_index,
                                   "label": f"{cand.institute_name} · {cand.role_name}"})
    config = build_config(
        body.week, {**body.profile, "coach_tone": body.coach_tone}, body.goal, options, body.last_ratings,
        [m.model_dump() for m in body.milestones], [c.model_dump() for c in body.cards], body.endpoints,
        body.start_tab, body.missed_previous_week)
    return HTMLResponse(render_input_fragment(config))


@app.post("/v1/recommendations", dependencies=[Depends(require_key)])
def recommendations(body: RecommendIn) -> dict:
    from .recommend import UserProfile, candidates_from_store, recommend

    s = store()
    try:
        roles = candidates_from_store(s, load_institutes())
    finally:
        s.close()
    recs = recommend(roles, UserProfile(**body.profile.model_dump()), [c.to_model() for c in body.cards],
                     body.top, body.include_closed)
    return {"candidates": len(roles), "items": [r.to_dict() for r in recs]}


@app.post("/v1/judge", dependencies=[Depends(require_key)])
def judge(body: JudgeIn) -> dict:
    from .goals import field_requirements
    from .llm.evidence import judge_card

    if (body.uid or "").strip():
        _, reqs = _role(body.uid, body.role_index)
    else:
        reqs = field_requirements(body.fields, _field_roles(), body.title or "")
        if not reqs:
            raise HTTPException(422, "이 분야의 공통 요구를 만들지 못했어요.")
    j = llm_errors(lambda: judge_card(llm(), body.card.to_model(), reqs))
    return {"card_id": j.card_id,
            "evidences": [{"requirement_id": e.requirement_id, "level": e.level, "card_id": e.card_id,
                           "quote": e.quote, "reason": j.reasons.get(e.requirement_id, "")} for e in j.evidences],
            "followup_questions": j.followup_questions, "dropped": len(j.dropped)}


@app.post("/v1/cards/draft", dependencies=[Depends(require_key)])
async def cards_draft(file: UploadFile = File(...)) -> dict:
    from .collector.extract import SUPPORTED, ext_of
    from .llm.card_draft import draft_cards_from_upload
    from .llm.ocr import IMAGE_TYPES

    name = file.filename or "upload"
    ext = ext_of(name)
    if (ext not in SUPPORTED and ext not in IMAGE_TYPES) or ext == ".zip":
        raise HTTPException(415, "PDF, HWP, HWPX, DOCX, TXT, 이미지(PNG·JPG·WEBP) 파일만 올릴 수 있어요.")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "파일은 10MB까지 올릴 수 있어요.")
    result = llm_errors(lambda: draft_cards_from_upload(llm(), name, data))
    return {"drafts": [{"card": d.card.__dict__, "source_quote": d.source_quote, "questions": d.questions}
                       for d in result.drafts],
            "rejected": result.rejected, "ocr_used": result.ocr_used}


@app.post("/v1/report", dependencies=[Depends(require_key)])
def report(body: ReportIn):
    from .metrics import MentoringRecord, ReportInputs, WeekState, build_report
    from .report_html import render, render_fragment

    goal = resolve_goal(body.goal)
    history = [WeekState(_checkin(w.checkin), [Evidence(**e.model_dump()) for e in w.evidences])
               for w in body.history]
    inp = ReportInputs(goal, history, [c.to_model() for c in body.cards], body.style_share,
                       [MentoringRecord(**m.model_dump()) for m in body.mentoring])
    data = build_report(inp, body.kind)

    feedback, healing = None, ""
    if body.with_feedback:
        from .feedback import build_weekly_feedback
        from .llm.feedback_writer import write_feedback
        from .scoring import axis_profile, prioritize_gaps

        now_w, prev_w = history[-1], history[-2] if len(history) > 1 else None
        now = axis_profile(goal, now_w.evidences, now_w.checkin.self_ratings)
        prev = axis_profile(goal, prev_w.evidences, prev_w.checkin.self_ratings) if prev_w else None
        plan = prioritize_gaps(goal, now_w.evidences, body.style_share)
        weekly = build_weekly_feedback(now, prev, now_w.checkin, plan, goal.weeks_left, body.coach_tone)
        written, healing = llm_errors(lambda: write_feedback(llm(), weekly, body.coach_tone, goal.title,
                                                             goal.weeks_left, [a["title"] for a in data["next_actions"]]))
        feedback = [{"kind": w.kind, "reason": w.reason, "text": w.text, "source": w.source} for w in written]
        data["feedback"], data["healing"] = feedback, healing

    if body.format == "html":
        return HTMLResponse(render(data, feedback, healing))
    if body.format == "html_fragment":
        return HTMLResponse(render_fragment(data, feedback, healing))
    return data
