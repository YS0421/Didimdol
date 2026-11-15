"""통합 CLI (LLM 호출 없는 기능).

  python -m didimdol_ai recommend [--profile ...] [--cards ...] [--top 5] [--include-closed] [--admin]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .collector.runner import load_institutes
from .collector.store import Store
from .models import ExperienceCard
from .recommend import UserProfile, candidates_from_store, recommend

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "collector_data" / "postings.sqlite3"


def load_profile(path: str) -> UserProfile:
    return UserProfile(**json.loads(Path(path).read_text(encoding="utf-8"))["profile"])


def load_cards(path: str) -> list[ExperienceCard]:
    return [ExperienceCard.from_dict(c) for c in json.loads(Path(path).read_text(encoding="utf-8"))["cards"]]


def judge_roles(recs, roles, cards):
    """상위 추천 직무에 대해 Claude 카드 판정 → {(uid, role_index): {req_id: Match}}."""
    from .llm.client import make_client
    from .llm.evidence import judge_card
    from .recommend import Match

    client = make_client()
    by_key = {(r.uid, r.role_index): r for r in roles}
    titles = {c.id: c.title for c in cards}
    out = {}
    for rec in recs:
        role = by_key[(rec.uid, rec.role_index)]
        if not role.requirements:
            continue
        labels = {q.id: q.label for q in role.requirements}
        best: dict[str, Match] = {}
        for card in cards:
            for ev in judge_card(client, card, role.requirements).evidences:
                if ev.requirement_id not in best or ev.level > best[ev.requirement_id].level:
                    best[ev.requirement_id] = Match(labels[ev.requirement_id], card.id, titles[card.id], ev.level, "판정")
        out[(rec.uid, rec.role_index)] = best
        print(f"(Claude 판정 완료: {role.institute_name} · {role.role_name})")
    return out


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="didimdol_ai")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rc = sub.add_parser("recommend")
    rc.add_argument("--profile", default=str(ROOT / "data" / "sample_profile.json"))
    rc.add_argument("--cards", default=str(ROOT / "data" / "sample_cards.json"))
    rc.add_argument("--top", type=int, default=5)
    rc.add_argument("--include-closed", action="store_true", help="마감된 공고도 포함 (데모용)")
    rc.add_argument("--admin", action="store_true", help="행정 직무도 포함")
    rc.add_argument("--judge", type=int, default=0,
                    help="상위 N개 직무는 Claude 카드 판정으로 근거를 다시 계산 (API 비용 발생)")
    rp = sub.add_parser("report", help="데모 이력으로 주간/월간 HTML 리포트 생성")
    rp.add_argument("--kind", default="monthly", choices=["weekly", "monthly"])
    rp.add_argument("--out", default=str(ROOT / "reports" / "demo_report.html"))
    args = ap.parse_args(argv)

    if args.cmd == "report":
        from .demo import history_inputs
        from .metrics import build_report
        from .report_html import render

        report = build_report(history_inputs(), args.kind)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render(report), encoding="utf-8")
        print(f"리포트 → {out}")
        return 0

    profile = load_profile(args.profile)
    if args.admin:
        profile.include_admin = True
    store = Store(str(DB))
    try:
        roles = candidates_from_store(store, load_institutes())
    finally:
        store.close()
    cards = load_cards(args.cards)
    recs = recommend(roles, profile, cards, args.top, args.include_closed)
    if args.judge and recs:
        judged = judge_roles(recs[: args.judge], roles, cards)
        recs = recommend(roles, profile, cards, args.top, args.include_closed, judged_by_role=judged)
    print(f"후보 직무 {len(roles)}개 → 추천 {len(recs)}개\n")
    for i, r in enumerate(recs, 1):
        ready = f"{r.readiness:.0%}" if r.readiness is not None else "정보 없음"
        print(f"{i}. [{r.bucket}] {r.institute} · {r.role_name}  (점수 {r.score}, 준비도 {ready})")
        print(f"   {r.title}")
        for reason in r.reasons:
            print(f"   - {reason}")
        for m in r.matches[:3]:
            print(f"   ↔ 카드 '{m.card_title}' → {m.requirement} (수준 {m.level}, {m.source})")
        for g in r.gaps:
            print(f"   ✎ 준비할 것: {g}")
        print()
    if not recs:
        print("조건에 맞는 직무가 없어요. --include-closed 또는 --admin 으로 범위를 넓혀 볼 수 있어요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
