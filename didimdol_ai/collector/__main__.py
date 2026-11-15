"""사용법:
  python -m didimdol_ai.collector run [--institutes kict,kist,kiom] [--pages 1] [--no-attachments]
  python -m didimdol_ai.collector export [--out postings.json] [--all] [--with-text]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .http import Fetcher
from .runner import collect_institute, load_institutes
from .store import Store

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = ROOT / "collector_data"


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔 한글 깨짐 방지
    ap = argparse.ArgumentParser(prog="didimdol_ai.collector")
    ap.add_argument("--data-dir", default=str(DEFAULT_DIR))
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--institutes", default="")
    run.add_argument("--pages", type=int, default=1)
    run.add_argument("--no-attachments", action="store_true")
    run.add_argument("--interval", type=float, default=2.0, help="같은 사이트 요청 간격(초)")
    exp = sub.add_parser("export")
    exp.add_argument("--out", default="")
    exp.add_argument("--all", action="store_true", help="제외된 공고까지 포함")
    exp.add_argument("--with-text", action="store_true", help="AI 분석용 본문·첨부 텍스트 포함")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(str(data_dir / "postings.sqlite3"))
    institutes = load_institutes()

    try:
        if args.cmd == "run":
            codes = [c for c in args.institutes.split(",") if c] or list(institutes)
            fetcher = Fetcher(min_interval=args.interval)
            had_problem = False
            for code in codes:
                if code not in institutes:
                    print(f"알 수 없는 기관: {code}")
                    had_problem = True
                    continue
                print(f"== {institutes[code]['name']} ({code})")
                res = collect_institute(code, fetcher, store, data_dir / "attachments",
                                        pages=args.pages, with_attachments=not args.no_attachments)
                print(f"   목록 {res.listed}건 · 학사 인턴 {res.included}건 · 신규 {res.new} · 변경 {res.changed}")
                for e in res.errors:
                    print(f"   ! {e}")
                if res.alert:
                    print(f"   ⚠ {res.alert}")
                had_problem |= bool(res.errors or res.alert)
            closed = store.mark_closed_by_date(date.today())
            print(f"마감 처리 {closed}건")
            for origin, note in fetcher.robots_notes.items():
                print(f"robots: {origin} — {note}")
            return 1 if had_problem else 0

        items = store.export(institutes, include_only=not args.all, with_text=args.with_text)
        text = json.dumps(items, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"{len(items)}건 → {args.out}")
        else:
            print(text)
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
