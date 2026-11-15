"""가상 학부생 예시 데이터셋 생성기 (LLM 호출 없음, 비용 0).

data/examples/<persona_id>/ 아래에 만든다.
- profile.json            온보딩 정보 (API ProfileIn 형식)
- cards.json              경험 카드 (API CardIn 형식) + 카드를 기록한 주(added_week)
- portfolio.txt           카드와 같은 내용을 자유 서술한 포트폴리오 (카드 초안 기능 시험용)
- portfolio_scan.png      portfolio.txt를 이미지로 만든 '스캔본' (Claude OCR 시험용)
- report_request.json     8주 체크인 이력 → POST /v1/report 요청 본문 그대로
- recommend_request.json  POST /v1/recommendations 요청 본문 그대로
- report_weekly.html, report_monthly.html, report.json   이 데이터로 계산한 리포트
- recommendations.json    이 데이터로 계산한 공고 추천 (어휘 추정)

모든 인물은 가상이다. 이름·학교 대신 persona_id만 쓴다(블라인드 원칙).
근거 수준은 Claude 판정 대신 어휘 추정(recommend.estimate_evidence)으로 만든다.
목표 직무는 수집 DB에 실제로 분석된 공고 직무를 쓰므로, DB가 바뀌면 결과도 달라진다.

실행: python scripts/make_examples.py
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from didimdol_ai.actions import next_actions  # noqa: E402
from didimdol_ai.collector.runner import load_institutes  # noqa: E402
from didimdol_ai.collector.store import Store  # noqa: E402
from didimdol_ai.feedback import build_weekly_feedback  # noqa: E402
from didimdol_ai.llm.requirements import Extraction  # noqa: E402
from didimdol_ai.metrics import MentoringRecord, ReportInputs, WeekState, build_report  # noqa: E402
from didimdol_ai.models import Checkin, Evidence, ExperienceCard, Goal, MilestoneResult  # noqa: E402
from didimdol_ai.recommend import UserProfile, candidates_from_store, estimate_evidence, recommend  # noqa: E402
from didimdol_ai.report_html import render  # noqa: E402
from didimdol_ai.scoring import axis_profile, prioritize_gaps  # noqa: E402

OUT = ROOT / "data" / "examples"
DB = ROOT / "collector_data" / "postings.sqlite3"
WEEKS = 8
HOLD_REASONS = ["time", "external", "unclear", "motivation"]


@dataclass
class Card:
    week: int  # 이 주 체크인 때 기록함 (0 = 시작 전부터 있던 기록)
    kind: str
    title: str
    actions: str
    role: str = ""
    period: str = ""
    tools: list[str] = field(default_factory=list)
    outcome: str = ""
    learned: str = ""


@dataclass
class Persona:
    pid: str
    summary: str
    grade: str
    status: str  # enrolled / expected / graduated
    interest_fields: list[str]
    regions: list[str]
    style_share: dict[str, float]
    weekly_hours: float
    coach_tone: str
    goal_uid: str
    goal_role: int
    weeks_left_at_start: int
    self_bias: float  # 자기평가 경향 (+ 과대, - 과소)
    low_condition_weeks: set[int]
    stuck_from: int  # 이 주부터 첫 번째 할 일이 계속 보류됨 (0이면 없음)
    missed_weeks: set[int]  # 체크인을 거른 주 (이력에서 빠짐)
    include_admin: bool
    cards: list[Card]
    mentoring: list[tuple[int, str, bool, bool]] = field(default_factory=list)


PERSONAS = [
    Persona(
        "p01_bio_lab", "3학년 재학 · 생명과학 · 학부연구생 4개월 · 자기평가 약간 높음", "3학년", "enrolled",
        ["chem"], ["대전"], {"analyze": 0.4, "make": 0.4, "talk": 0.1, "plan": 0.1}, 8, "balanced",
        "kribb:35443", 3, 10, 0.5, {4}, 0, set(), False,
        [
            Card(0, "수업", "생화학·분자생물학 수강", "생화학, 분자생물학, 세포생물학 과목을 수강했다. 단백질 구조와 세포사멸 기전을 배웠다.",
                 period="2025.03-2025.12", tools=["SDS-PAGE"]),
            Card(0, "학부연구생", "세포배양 실험 보조", "선배가 정한 프로토콜대로 세포배양을 하고 웨스턴 블롯으로 단백질 발현을 확인했다. "
                 "실험 결과를 연구노트에 정리했다.", role="학부연구생", period="2026.03-2026.06",
                 tools=["세포배양", "Western blot"], outcome="연구노트 4개월분"),
            Card(3, "수업 프로젝트", "분자생물학 실험 기말 프로젝트", "PCR 조건을 직접 설계해 유전자 증폭 실험을 하고, 전기영동 결과를 "
                 "분석해 보고서를 썼다.", role="팀장", period="2026.09-2026.12", tools=["PCR", "전기영동"],
                 learned="조건을 바꾸면 결과가 어떻게 달라지는지 체계적으로 기록하는 법을 배웠다."),
            Card(6, "독학", "연구윤리 온라인 교육 이수", "연구윤리정보센터 온라인 교육으로 연구윤리와 연구노트 작성 원칙을 공부했다.",
                 tools=[]),
        ],
        [(2, "학부연구생 경험을 지원서에 어떻게 쓰면 좋을까요?", True, True),
         (6, "단백질 구조 분석을 혼자 공부하려면 무엇부터 보면 될까요?", True, False)],
    ),
    Persona(
        "p02_ai_omics", "4학년 졸업예정 · 컴퓨터공학+생명 복수전공 · 데이터 프로젝트 다수 · 자기평가 낮음", "4학년", "expected",
        ["ai", "it", "chem"], [], {"analyze": 0.6, "make": 0.2, "talk": 0.1, "plan": 0.1}, 10, "praise",
        "kribb:35443", 4, 8, -1.0, set(), 0, {5}, False,
        [
            Card(0, "수업 프로젝트", "머신러닝 수업 프로젝트", "공개 유전자 발현 데이터로 암 아형 분류 모델을 Python과 scikit-learn으로 "
                 "직접 설계하고 학습시켰다. 기계학습 모델의 성능을 교차검증으로 비교했다.", role="팀장",
                 period="2025.09-2025.12", tools=["Python", "scikit-learn", "pandas"], outcome="기말 발표"),
            Card(0, "독학", "바이오인포매틱스 온라인 강의", "유전체분석과 오믹스 데이터 처리 기초를 온라인 강의로 공부했다.",
                 tools=["R"]),
            Card(2, "공모전", "헬스케어 데이터 분석 공모전", "의료 데이터 전처리와 시각화를 맡아 Python으로 분석 파이프라인을 "
                 "만들었다. 팀 보고서의 데이터 분석 파트를 작성했다.", role="데이터 분석 담당", period="2026.07-2026.08",
                 tools=["Python", "matplotlib"], outcome="장려상"),
            Card(5, "독학", "생명정보학 미니 프로젝트", "공개 RNA-seq 데이터로 차등발현 유전자 분석을 스스로 기획해 수행하고 "
                 "결과를 블로그에 정리했다.", tools=["Python", "DESeq2"], learned="오믹스 데이터 정규화가 결과를 크게 바꾼다."),
        ],
        [(3, "AI 직무 인턴 면접에서 프로젝트를 어떻게 설명하면 좋을까요?", True, True)],
    ),
    Persona(
        "p03_energy_h2", "4학년 졸업예정 · 화학공학 · 전기화학 수업 위주 · 시간 여유 보통", "4학년", "expected",
        ["energy", "chem", "material"], ["대전"], {"analyze": 0.3, "make": 0.5, "talk": 0.1, "plan": 0.1}, 6, "direct",
        "kier:262563", 13, 9, 0.0, {6, 7}, 4, set(), False,
        [
            Card(0, "수업", "전기화학 수강", "전기화학과 물리화학 과목을 수강해 수전해와 연료전지의 원리를 배웠다.", period="2026.03-2026.06"),
            Card(0, "수업 프로젝트", "전기화학 실험 수업", "주어진 조건으로 순환전압전류법 측정을 하고 전기화학적 분석 결과를 "
                 "엑셀로 정리했다.", period="2026.03-2026.06", tools=["CV", "Excel"]),
            Card(5, "독학", "수소 생산 기술 자료 정리", "수소 생산과 수전해 방식별 특징을 논문 리뷰로 공부하고 요약 노트를 만들었다."),
        ],
        [(1, "세라믹 합성 경험이 없는데 지원해도 될까요?", True, True)],
    ),
    Persona(
        "p04_mech_energy", "4학년 졸업예정 · 기계공학 · 캡스톤 설계 · 자기평가 높음(근거보다 앞섬)", "4학년", "expected",
        ["mech", "energy"], [], {"analyze": 0.2, "make": 0.6, "talk": 0.1, "plan": 0.1}, 6, "direct",
        "kier:262563", 24, 8, 1.5, set(), 5, set(), False,
        [
            Card(0, "수업", "열역학·유체역학 수강", "열역학, 유체역학, 열전달 과목을 수강했다.", period="2024.03-2025.12"),
            Card(0, "수업 프로젝트", "캡스톤 디자인", "소형 열교환기 시제품의 설계 도면을 CAD 설계 소프트웨어로 직접 작성하고 "
                 "열해석 결과를 보고서로 정리했다.", role="설계 담당", period="2026.03-2026.06",
                 tools=["SolidWorks", "ANSYS"], outcome="캡스톤 경진대회 발표"),
        ],
        [],
    ),
    Persona(
        "p05_admin_comm", "2학년 재학 · 미디어커뮤니케이션 · 동아리 홍보 · 주당 시간 적음 · 컨디션 기복", "2학년", "enrolled",
        [], ["서울"], {"analyze": 0.1, "make": 0.1, "talk": 0.5, "plan": 0.3}, 3, "praise",
        "kist:18304", 4, 16, 0.0, {2, 3, 6}, 3, {4}, True,
        [
            Card(0, "동아리", "과학 동아리 홍보 담당", "동아리 SNS 콘텐츠 기획과 카드뉴스 제작을 맡았다. 게시물 반응 결과를 분석해 "
                 "다음 홍보방법을 정했다.", role="홍보부장", period="2025.03-2026.02", tools=["Canva", "Instagram"]),
            Card(5, "수업", "미디어와 언론 수강", "언론의 종류별 특성과 콘텐츠 유형별 특성을 배우는 전공 과목을 수강했다."),
        ],
        [(5, "행정인턴은 어떤 준비를 하면 좋을까요?", False, False)],
    ),
]


# ---------------------------------------------------------------- 생성


def load_goal(store: Store, uid: str, idx: int) -> tuple[str, list]:
    ext = store.get_extraction(uid)
    if not ext:
        raise SystemExit(f"{uid} 분석 결과가 DB에 없어요. 먼저 python -m didimdol_ai.llm extract 를 실행하세요.")
    role = ext["roles"][idx]
    return role["role_name"], Extraction(ext["uid"], ext["model"], ext["roles"]).to_requirements(idx)


def to_card(p: Persona, i: int, c: Card) -> ExperienceCard:
    return ExperienceCard(f"{p.pid}-c{i + 1}", c.kind, c.title, c.actions, c.role, c.period, c.tools, c.outcome, c.learned)


def evidences_for(reqs, cards: list[ExperienceCard], threshold: float) -> list[Evidence]:
    out = []
    for r in reqs:
        m = estimate_evidence(r, cards, threshold)
        if m:
            card = next(c for c in cards if c.id == m.card_id)
            out.append(Evidence(r.id, m.level, card.id, card.actions[:40]))
    return out


def build_persona(p: Persona, store: Store, rng: random.Random) -> dict:
    from didimdol_ai.config import load_planning

    threshold = load_planning()["recommend"]["match_threshold"]
    role_name, reqs = load_goal(store, p.goal_uid, p.goal_role)
    cards = [to_card(p, i, c) for i, c in enumerate(p.cards)]
    history, request_weeks, prev_actions, hold_streak = [], [], [], 0

    for w in range(1, WEEKS + 1):
        if w in p.missed_weeks:
            continue
        have = [c for c, src in zip(cards, p.cards) if src.week <= w]
        weeks_left = max(0, p.weeks_left_at_start - (w - 1))
        goal = Goal(p.goal_uid, role_name, reqs, weeks_left, p.weekly_hours)
        ev = evidences_for(reqs, have, threshold)
        prof = axis_profile(goal, ev)
        # 자기평가: 근거 점수 + 성향 + 주차에 따른 자신감 변화(작은 흔들림)
        ratings = {}
        for a, s in prof.items():
            if s.target is None:
                continue
            base = (s.evidence or 1.5) + p.self_bias + rng.choice([-0.4, 0, 0, 0.4])
            ratings[a] = max(1, min(5, round(base)))
        # 마일스톤: 지난주 제안된 할 일의 결과
        ms = []
        for k, act in enumerate(prev_actions[:2]):
            if p.stuck_from and w >= p.stuck_from and k == 0:
                hold_streak += 1
                ms.append(MilestoneResult(f"m-{act.requirement_id}", act.title, "on_hold",
                                          HOLD_REASONS[(w + k) % 4], hold_streak, act.requirement_id))
            else:
                status = "done" if rng.random() < 0.55 else "in_progress"
                ms.append(MilestoneResult(f"m-{act.requirement_id}", act.title, status,
                                          requirement_id=act.requirement_id))
        condition = 2 if w in p.low_condition_weeks else rng.choice([3, 4, 4, 5])
        hours = round(p.weekly_hours * rng.uniform(0.4, 1.2), 1)
        checkin = Checkin(f"W{w}", ratings, ms, hours, condition, missed_previous_week=(w - 1) in p.missed_weeks)
        history.append(WeekState(checkin, ev))
        request_weeks.append({
            "checkin": {"week": checkin.week, "self_ratings": ratings, "milestones": [asdict(m) for m in ms],
                        "hours_spent": hours, "condition": condition,
                        "missed_previous_week": checkin.missed_previous_week},
            "evidences": [asdict(e) for e in ev],
        })
        stuck = {m.requirement_id for m in ms if m.status == "on_hold" and m.consecutive_hold_weeks >= 2}
        new_actions = next_actions(prioritize_gaps(goal, ev, p.style_share).items, 2, stuck)
        if p.stuck_from and w >= p.stuck_from and prev_actions:
            new_actions = [prev_actions[0]] + [a for a in new_actions if a.requirement_id != prev_actions[0].requirement_id][:1]
        prev_actions = new_actions

    final_goal = Goal(p.goal_uid, role_name, reqs, max(0, p.weeks_left_at_start - WEEKS + 1), p.weekly_hours)
    mentoring = [MentoringRecord(f"W{w}", q, a, f) for w, q, a, f in p.mentoring]
    inp = ReportInputs(final_goal, history, cards, p.style_share, mentoring)

    # 주간 피드백(템플릿 문장)
    now_w, prev_w = history[-1], history[-2]
    now = axis_profile(final_goal, now_w.evidences, now_w.checkin.self_ratings)
    prev = axis_profile(final_goal, prev_w.evidences, prev_w.checkin.self_ratings)
    plan = prioritize_gaps(final_goal, now_w.evidences, p.style_share)
    wf = build_weekly_feedback(now, prev, now_w.checkin, plan, final_goal.weeks_left, p.coach_tone)
    feedback = [{"kind": i.kind, "reason": i.reason, "text": i.message, "source": "template"} for i in wf.items]
    healing = "이번 주는 숲에서 잠깐 쉬어 가도 괜찮아요." if wf.suggest_healing else ""

    weekly, monthly = build_report(inp, "weekly"), build_report(inp, "monthly")
    monthly["feedback"], monthly["healing"] = feedback, healing

    profile = {"status": p.status, "interest_fields": p.interest_fields, "regions": p.regions,
               "style_share": p.style_share, "weekly_hours": p.weekly_hours, "include_admin": p.include_admin}
    card_json = [{**asdict(c), "added_week": src.week} for c, src in zip(cards, p.cards)]
    recs = recommend(candidates_from_store(store, load_institutes()), UserProfile(**profile), cards, top=5,
                     include_closed=True)
    return {
        "role_name": role_name, "reqs": reqs, "profile": profile, "cards": card_json, "feedback": feedback,
        "healing": healing, "weekly": weekly, "monthly": monthly, "recs": recs,
        "report_request": {
            "goal": {"uid": p.goal_uid, "role_index": p.goal_role, "weeks_left": final_goal.weeks_left,
                     "weekly_hours": p.weekly_hours},
            "history": request_weeks, "cards": [asdict(c) for c in cards], "style_share": p.style_share,
            "mentoring": [asdict(m) for m in mentoring], "kind": "monthly", "format": "json",
            "with_feedback": False, "coach_tone": p.coach_tone,
        },
    }


def portfolio_text(p: Persona) -> str:
    lines = [f"포트폴리오 ({p.grade}, 가상 인물 {p.pid})", ""]
    for c in p.cards:
        head = f"■ {c.title}" + (f" ({c.period})" if c.period else "") + (f" - {c.role}" if c.role else "")
        lines += [head, c.actions]
        if c.tools:
            lines.append("사용 도구: " + ", ".join(c.tools))
        if c.outcome:
            lines.append("결과: " + c.outcome)
        if c.learned:
            lines.append("배운 점: " + c.learned)
        lines.append("")
    return "\n".join(lines)


def scan_image(text: str, path: Path) -> bool:
    """텍스트를 A4 비율 이미지로 그린 '스캔본'. 한글 글꼴이 없으면 만들지 않는다."""
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except ImportError:
        return False
    font_path = next((f for f in ("C:/Windows/Fonts/malgun.ttf", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf")
                      if Path(f).exists()), None)
    if not font_path:
        return False
    font = ImageFont.truetype(font_path, 22)
    wrapped = []
    for line in text.splitlines():
        while len(line) > 44:
            wrapped.append(line[:44])
            line = line[44:]
        wrapped.append(line)
    img = Image.new("L", (1100, max(1400, 80 + 36 * len(wrapped))), 250)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(wrapped):
        draw.text((70, 60 + 36 * i), line, fill=25, font=font)
    img = img.rotate(0.6, fillcolor=250).filter(ImageFilter.GaussianBlur(0.5))  # 살짝 기울고 흐린 스캔 느낌
    img.save(path, optimize=True)
    return True


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    rng = random.Random(20261115)
    OUT.mkdir(parents=True, exist_ok=True)
    store = Store(str(DB))
    index = []
    try:
        for p in PERSONAS:
            d = build_persona(p, store, rng)
            pdir = OUT / p.pid
            pdir.mkdir(exist_ok=True)

            def dump(name, obj):
                (pdir / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

            dump("profile.json", {"note": "가상 학부생 (실존 인물 아님)", "persona_id": p.pid, "summary": p.summary,
                                  "grade": p.grade, "coach_tone": p.coach_tone, "profile": d["profile"]})
            dump("cards.json", {"note": "added_week: 이 주 체크인 때 기록한 카드 (0 = 시작 전부터 있던 기록)",
                                "cards": d["cards"]})
            text = portfolio_text(p)
            (pdir / "portfolio.txt").write_text(text, encoding="utf-8")
            has_scan = scan_image(text, pdir / "portfolio_scan.png")
            dump("report_request.json", d["report_request"])
            dump("recommend_request.json", {"profile": d["profile"], "cards": [
                {k: v for k, v in c.items() if k != "added_week"} for c in d["cards"]], "top": 5, "include_closed": True})
            dump("report.json", d["monthly"])
            dump("recommendations.json", [r.to_dict() for r in d["recs"]])
            (pdir / "report_weekly.html").write_text(render(d["weekly"], d["feedback"], d["healing"]), encoding="utf-8")
            (pdir / "report_monthly.html").write_text(render(d["monthly"], d["feedback"], d["healing"]),
                                                      encoding="utf-8")
            gp = d["monthly"]["goal_progress"]
            index.append({"persona_id": p.pid, "summary": p.summary, "goal": f"{p.goal_uid}#{p.goal_role} {d['role_name']}",
                          "weeks_recorded": len(d["report_request"]["history"]), "cards": len(d["cards"]),
                          "goal_achievement": gp.get("achievement"), "scan_png": has_scan,
                          "top_recommendation": d["recs"][0].role_name if d["recs"] else None})
            print(f"{p.pid}: 목표 '{d['role_name'][:30]}' · 체크인 {len(d['report_request']['history'])}주 · "
                  f"카드 {len(d['cards'])}장 · 달성도 {gp.get("achievement")} · 추천 1위 "
                  f"{d['recs'][0].role_name[:30] if d['recs'] else '-'}")
    finally:
        store.close()
    (OUT / "index.json").write_text(json.dumps({"note": "가상 학부생 예시 데이터셋. scripts/make_examples.py로 다시 만들 수 있음.",
                                                "personas": index}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
