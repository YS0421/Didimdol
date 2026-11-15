"""사용법:
  python -m didimdol_ai.llm check                       # 키·모델 연결 확인 (아주 짧은 요청 1회)
  python -m didimdol_ai.llm extract [--limit 3] [--uid kist:18542] [--force] [--dry-run]
  python -m didimdol_ai.llm show --uid kist:18542
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import anthropic

from ..collector.runner import load_institutes
from ..collector.store import Store
from .client import make_client, model_name
from .requirements import ExtractionError, SkipExtraction, build_document, extract_requirements

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "collector_data" / "postings.sqlite3"


def _api_error_message(e: Exception) -> str:
    if isinstance(e, anthropic.AuthenticationError):
        return "인증 실패: .env의 ANTHROPIC_API_KEY가 올바른 Claude API 키(sk-ant-api…)인지 확인해 주세요."
    if isinstance(e, anthropic.PermissionDeniedError):
        return "권한 없음: 이 키로 해당 모델·기능을 쓸 수 없어요."
    if isinstance(e, anthropic.NotFoundError):
        return f"모델을 찾을 수 없어요: {model_name()}"
    if isinstance(e, anthropic.RateLimitError):
        return "요청 한도 초과: 잠시 후 다시 실행해 주세요."
    if isinstance(e, anthropic.APIStatusError):
        return f"API 오류 {e.status_code}: {e.message}"
    if isinstance(e, anthropic.APIConnectionError):
        return "네트워크 오류: 인터넷 연결을 확인해 주세요."
    return str(e)


def run_judge(args) -> int:
    import json

    from ..config import axis_names
    from ..models import ExperienceCard, Goal
    from ..scoring import axis_profile, prioritize_gaps
    from .evidence import judge_card
    from .requirements import Extraction

    store = Store(str(DB))
    try:
        stored = store.get_extraction(args.uid)
    finally:
        store.close()
    if not stored:
        print("이 공고의 요구 항목 추출 결과가 없어요. 먼저 extract를 실행해 주세요.")
        return 1
    ext = Extraction(stored["uid"], stored["model"], stored["roles"])
    role = ext.roles[args.role]
    reqs = ext.to_requirements(args.role)
    cards = [ExperienceCard(**c) for c in json.loads(Path(args.cards).read_text(encoding="utf-8"))["cards"]]
    ratings = json.loads(args.ratings) if args.ratings else {}
    labels = {r.id: r.label for r in reqs}

    print(f"목표: {args.uid} [{args.role}] {role['role_name']} · 요구 항목 {len(reqs)}개 · 카드 {len(cards)}장\n")
    client = make_client()
    evidences = []
    for card in cards:
        try:
            j = judge_card(client, card, reqs)
        except (ExtractionError, anthropic.APIError) as e:
            print(f"카드 {card.id} 판정 실패: {_api_error_message(e)}")
            return 1
        evidences += j.evidences
        print(f"■ 카드 {card.id} '{card.title}' — 근거 {len(j.evidences)}개 (버림 {len(j.dropped)})")
        for ev in j.evidences:
            print(f"   - {labels[ev.requirement_id]}: 수준 {ev.level} ← \"{ev.quote}\"")
            print(f"     이유: {j.reasons[ev.requirement_id]}")
        for q in j.followup_questions:
            print(f"   ? 보충 질문: {q}")

    goal = Goal(args.uid, role["role_name"], reqs, args.weeks, args.hours)
    names = axis_names()
    quad = {"record_proof": "기록·증명", "maintain_expand": "유지·확장",
            "learn_experience": "학습·경험", "confidence_expression": "자신감·표현"}
    print("\n■ 육각형 (목표선 / 근거 점수 / 자기평가 → 방향)")
    for axis, s in axis_profile(goal, evidences, ratings).items():
        if s.target is None:
            print(f"   {names[axis]:<10} 이 직무와 연결된 요구 항목 없음")
            continue
        self_txt = s.self_rating if s.self_rating is not None else "-"
        print(f"   {names[axis]:<10} 목표 {s.target} / 근거 {s.evidence} / 자기평가 {self_txt}"
              + (f" → {quad[s.quadrant]}" if s.quadrant else ""))

    plan = prioritize_gaps(goal, evidences)
    print(f"\n■ 다음 한 칸 (가용 {plan.available_hours:.0f}시간, 필요 {plan.total_cost_hours:.0f}시간"
          + (", 목표·기한 조정 필요" if plan.needs_adjustment else "") + ")")
    if not plan.items:
        print("   이 직무의 요구 수준을 모두 기록으로 뒷받침하고 있어요. 더 높은 수준의 목표나 다른 직무를 골라 볼 수 있어요.")
    for g in plan.items[:5]:
        print(f"   {'✓' if g.fits_plan else '…'} {g.requirement.label}: 수준 {g.current_level} → {g.requirement.required_level}"
              f" ({g.requirement.necessity}, 예상 {g.cost_hours:.0f}시간)")
    for req, ok in plan.checklist:
        print(f"   [{'x' if ok else ' '}] 체크리스트: {req.label}")

    from ..actions import next_actions
    acts = next_actions(plan.items)
    if acts:
        print("\n■ 이번에 해 볼 행동")
        for a in acts:
            print(f"   • {a.title} (약 {a.hours:.0f}시간, 수준 {a.from_level}→{a.to_level})")
            print(f"     {a.how}")
            if a.card_kind:
                print(f"     끝나면 '{a.card_kind}' 경험 카드로 남겨요 · 근거: \"{a.source_quote}\"")
    return 0


def run_draft(args) -> int:
    from .card_draft import draft_cards_from_file

    try:
        result = draft_cards_from_file(make_client(), args.file)
    except Exception as e:
        print(_api_error_message(e))
        return 1
    ocr = " · 스캔/이미지라 Claude OCR로 읽음" if result.ocr_used else ""
    print(f"카드 초안 {len(result.drafts)}장 · 검증 탈락 {len(result.rejected)}장 · 토큰 {result.usage}{ocr}\n")
    for d in result.drafts:
        c = d.card
        print(f"■ [{c.kind}] {c.title} ({c.period or '기간 미상'}) · 역할: {c.role or '-'}")
        print(f"   행동: {c.actions}")
        if c.tools:
            print(f"   도구: {', '.join(c.tools)}")
        if c.outcome:
            print(f"   결과: {c.outcome}")
        print(f"   근거: \"{d.source_quote}\"")
        for q in d.questions:
            print(f"   ? {q}")
    for r in result.rejected:
        print(f"✗ 탈락: {r['title']} — {r['reason']}")
    return 0


def run_feedback(args) -> int:
    from ..demo import scenario
    from .feedback_writer import write_feedback

    kinds = {"praise": "칭찬", "encourage": "격려", "push": "채찍질"}
    tones = ["praise", "balanced", "direct"] if args.tone == "all" else [args.tone]
    client = make_client()
    for tone in tones:
        goal, weekly, plan = scenario(args.condition, tone)
        steps = [g.requirement.label for g in plan.items if g.fits_plan][:2]
        label = {"praise": "칭찬형", "balanced": "균형형", "direct": "직설형"}[tone]
        print(f"■ 코치 톤: {label}" + (f" · 컨디션 {args.condition}" if args.condition else ""))
        print(f"   규칙 엔진 후보 {len(weekly.all_candidates)}개 → 이번 주 {len(weekly.items)}개 선택")
        try:
            written, healing = write_feedback(client, weekly, tone, goal.title, goal.weeks_left, steps)
        except anthropic.APIError as e:
            print(f"   ! {_api_error_message(e)}")
            return 1
        for w in written:
            tag = "" if w.source == "llm" else f"  (템플릿 사용: {w.rejected_reason})"
            print(f"   [{kinds[w.kind]}·{w.reason}] {w.text}{tag}")
        if healing:
            print(f"   [숲 힐링] {healing}")
        print()
    return 0


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="didimdol_ai.llm")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    ex = sub.add_parser("extract")
    ex.add_argument("--limit", type=int, default=0)
    ex.add_argument("--uid", default="")
    ex.add_argument("--force", action="store_true", help="이미 분석한 공고도 다시 분석")
    ex.add_argument("--dry-run", action="store_true", help="API 호출 없이 대상과 입력 길이만 출력")
    sh = sub.add_parser("show")
    sh.add_argument("--uid", required=True)
    jd = sub.add_parser("judge", help="경험 카드 → 목표 직무 요구 항목별 근거 판정 → 육각형·갭 리포트")
    jd.add_argument("--uid", required=True, help="목표 공고 uid (예: kiom:20233)")
    jd.add_argument("--role", type=int, default=0, help="공고 안의 직무 번호 (show로 확인)")
    jd.add_argument("--cards", default=str(ROOT / "data" / "sample_cards.json"))
    jd.add_argument("--ratings", default="", help='자기평가 JSON (예: {"research":4,"data":3})')
    jd.add_argument("--weeks", type=int, default=8)
    jd.add_argument("--hours", type=float, default=8)
    fb = sub.add_parser("feedback", help="데모 시나리오로 주간 피드백 문장 생성 (코치 톤별 비교)")
    fb.add_argument("--tone", default="all", choices=["all", "praise", "balanced", "direct"])
    fb.add_argument("--condition", type=int, default=None, help="컨디션 1~5 (2 이하이면 채찍질 억제)")
    dr = sub.add_parser("draft", help="포트폴리오 파일 → 경험 카드 초안")
    dr.add_argument("--file", default=str(ROOT / "data" / "sample_portfolio.txt"))
    args = ap.parse_args(argv)

    if args.cmd == "draft":
        return run_draft(args)
    if args.cmd == "judge":
        return run_judge(args)
    if args.cmd == "feedback":
        return run_feedback(args)

    if args.cmd == "check":
        try:
            client = make_client()
            r = client.messages.create(
                model=model_name(), max_tokens=64, output_config={"effort": "low"},
                messages=[{"role": "user", "content": "연결 확인입니다. '정상'이라고만 답해 주세요."}],
            )
            text = next((b.text for b in r.content if b.type == "text"), "")
            print(f"연결 성공 · 모델 {r.model} · 응답: {text.strip()}")
            return 0
        except Exception as e:
            print(_api_error_message(e))
            return 1

    store = Store(str(DB))
    try:
        if args.cmd == "show":
            result = store.get_extraction(args.uid)
            if not result:
                print("추출 결과가 없어요.")
                return 1
            for i, role in enumerate(result["roles"]):
                ncs = role.get("ncs")
                ncs_text = " > ".join(ncs[k] for k in ("major", "middle", "minor", "detail")) if ncs else "없음"
                ug = role["eligibility"].get("undergrad_eligible")
                ug_text = {True: "학부생 가능", False: "학부생 불가", None: "학부생 여부 미판정"}[ug]
                print(f"[{i}] {role['role_name']} · {role['category']} · 분야 {role['fields']} · "
                      f"{ug_text} · 대상 {role['eligibility']['targets']} · NCS {ncs_text}")
                for r in role["requirements"]:
                    print(f"    - ({r['necessity']}, 수준 {r['required_level']}, 축 {r['axes'] or '체크리스트'}) "
                          f"{r['label']}  ← \"{r['quote']}\"")
            if result["dropped"]:
                print(f"  인용 검증 실패로 버린 항목 {len(result['dropped'])}개")
            return 0

        institutes = load_institutes()
        postings = {p["uid"]: p for p in store.export(institutes, with_text=True)}
        if args.uid:
            uids = [args.uid]
        elif args.force:
            uids = list(postings)
        else:
            uids = store.pending_analysis()
        if args.limit:
            uids = uids[: args.limit]
        if not uids:
            print("분석할 공고가 없어요.")
            return 0

        if args.dry_run:
            for uid in uids:
                print(f"{uid}  {postings[uid]['title']}  입력 {len(build_document(postings[uid])):,}자")
            return 0

        client = make_client()
        failed = 0
        for uid in uids:
            p = postings[uid]
            print(f"== {uid} {p['title']}")
            try:
                ext = extract_requirements(client, p)
            except SkipExtraction as e:
                print(f"   - {e}")
                continue
            except (ExtractionError, anthropic.APIError) as e:
                print(f"   ! {_api_error_message(e)}")
                failed += 1
                if isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
                    break
                continue
            store.save_extraction(uid, ext.model, ext.to_json())
            n = sum(len(r["requirements"]) for r in ext.roles)
            print(f"   직무 {len(ext.roles)}개 · 요구 항목 {n}개 · 인용 검증 실패 {len(ext.dropped)}개 · "
                  f"토큰 입력 {ext.usage.get('input_tokens')} / 출력 {ext.usage.get('output_tokens')}")
        return 1 if failed else 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
