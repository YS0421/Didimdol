"""SQLite 공고 이력 저장소. 마감 공고도 지우지 않고 보관한다 (분야별 요구 빈도 분석용)."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import date, datetime
from typing import Optional

from .models import Posting

SCHEMA = """
CREATE TABLE IF NOT EXISTS postings (
    uid TEXT PRIMARY KEY,
    institute TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    dedup_key TEXT NOT NULL,
    url TEXT NOT NULL,
    posted_on TEXT, apply_start_on TEXT, apply_end_on TEXT,
    status_text TEXT,
    include INTEGER NOT NULL,
    exclude_reason TEXT,
    category TEXT,
    targets TEXT,
    is_closed INTEGER NOT NULL,
    body_text TEXT,
    content_hash TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    analyzed_hash TEXT              -- AI 요구 항목 추출이 끝난 content_hash (변경 시 재분석)
);
CREATE INDEX IF NOT EXISTS idx_postings_dedup ON postings(dedup_key);
CREATE TABLE IF NOT EXISTS attachments (
    uid TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT,
    local_path TEXT,
    text TEXT,
    skipped_reason TEXT,
    PRIMARY KEY (uid, name)
);
CREATE TABLE IF NOT EXISTS extractions (
    uid TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,     -- 분석한 시점의 공고 내용 해시
    model TEXT NOT NULL,
    extracted_at TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    started_at TEXT NOT NULL,
    institute TEXT NOT NULL,
    listed INTEGER, included INTEGER, new INTEGER, changed INTEGER,
    errors TEXT
);
"""


def _d(v: Optional[date]) -> Optional[str]:
    return v.isoformat() if v else None


def dedup_key(institute: str, title: str, apply_end: Optional[date]) -> str:
    """출처가 달라도 같은 공고를 찾기 위한 키 (기관 + 정규화 제목 + 마감일)."""
    norm = re.sub(r"[\s\[\]()<>「」『』·,.\-_:]+", "", title).lower()
    return f"{institute}|{norm}|{_d(apply_end) or ''}"


def content_hash(p: Posting) -> str:
    payload = json.dumps(
        [p.ref.title, _d(p.ref.apply_start_on), _d(p.ref.apply_end_on), p.body_text,
         sorted((a.name, a.text) for a in p.attachments)],
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def text_hash(body_text: str, attachments: list[tuple[str, str]]) -> str:
    """AI 재분석 여부 판단용: 본문·첨부 텍스트만 본다 (날짜·제목 표기 변경으로는 재분석하지 않음)."""
    payload = json.dumps([body_text or "", sorted((n, t or "") for n, t in attachments)], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(postings)")}
        if "text_hash" in cols:
            return
        self.db.execute("ALTER TABLE postings ADD COLUMN text_hash TEXT")
        for row in self.db.execute("SELECT uid, body_text, content_hash, analyzed_hash FROM postings").fetchall():
            atts = [(a["name"], a["text"]) for a in
                    self.db.execute("SELECT name, text FROM attachments WHERE uid=?", (row["uid"],))]
            th = text_hash(row["body_text"], atts)
            analyzed = th if row["analyzed_hash"] and row["analyzed_hash"] == row["content_hash"] else row["analyzed_hash"]
            self.db.execute("UPDATE postings SET text_hash=?, analyzed_hash=? WHERE uid=?", (th, analyzed, row["uid"]))
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def known_hash(self, uid: str) -> Optional[str]:
        row = self.db.execute("SELECT content_hash FROM postings WHERE uid=?", (uid,)).fetchone()
        return row["content_hash"] if row else None

    def upsert(self, p: Posting, now: Optional[str] = None) -> str:
        """'new' | 'changed' | 'same' 을 돌려준다."""
        now = now or datetime.now().isoformat(timespec="seconds")
        h = content_hash(p)
        prev = self.db.execute("SELECT content_hash, revision FROM postings WHERE uid=?", (p.uid,)).fetchone()
        r = p.ref
        values = dict(
            uid=p.uid, institute=r.institute, external_id=r.external_id, title=r.title,
            dedup_key=dedup_key(r.institute, r.title, r.apply_end_on), url=r.url,
            posted_on=_d(r.posted_on), apply_start_on=_d(r.apply_start_on), apply_end_on=_d(r.apply_end_on),
            status_text=r.status_text, include=int(p.include), exclude_reason=p.exclude_reason,
            category=p.category, targets=json.dumps(p.targets), is_closed=int(p.is_closed),
            body_text=p.body_text, content_hash=h, last_seen=now,
            text_hash=text_hash(p.body_text, [(a.name, a.text) for a in p.attachments]),
        )
        if prev is None:
            status = "new"
            self.db.execute(
                f"INSERT INTO postings ({', '.join(values)}, revision, first_seen) "
                f"VALUES ({', '.join('?' * len(values))}, 1, ?)",
                [*values.values(), now],
            )
        else:
            status = "same" if prev["content_hash"] == h else "changed"
            rev = prev["revision"] + (1 if status == "changed" else 0)
            sets = ", ".join(f"{k}=?" for k in values if k != "uid")
            self.db.execute(
                f"UPDATE postings SET {sets}, revision=? WHERE uid=?",
                [v for k, v in values.items() if k != "uid"] + [rev, p.uid],
            )
        if status != "same":
            self.db.execute("DELETE FROM attachments WHERE uid=?", (p.uid,))
            self.db.executemany(
                "INSERT OR REPLACE INTO attachments VALUES (?,?,?,?,?,?)",
                [(p.uid, a.name, a.url, a.local_path, a.text, a.skipped_reason) for a in p.attachments],
            )
        self.db.commit()
        return status

    def mark_closed_by_date(self, today: date) -> int:
        cur = self.db.execute(
            "UPDATE postings SET is_closed=1 WHERE is_closed=0 AND apply_end_on IS NOT NULL AND apply_end_on < ?",
            (today.isoformat(),),
        )
        self.db.commit()
        return cur.rowcount

    def log_run(self, started_at: str, institute: str, listed: int, included: int,
                new: int, changed: int, errors: list[str]) -> None:
        self.db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
                        (started_at, institute, listed, included, new, changed, json.dumps(errors, ensure_ascii=False)))
        self.db.commit()

    def recent_zero_runs(self, institute: str, n: int = 2) -> bool:
        """최근 n번 연속 목록 0건이면 True (게시판 구조 변경 의심)."""
        rows = self.db.execute(
            "SELECT listed FROM runs WHERE institute=? ORDER BY started_at DESC LIMIT ?", (institute, n)
        ).fetchall()
        return len(rows) == n and all(r["listed"] == 0 for r in rows)

    # ------------------------------------------------------------ AI 추출 결과

    def pending_analysis(self) -> list[str]:
        """학사 인턴 공고 중 아직 분석 안 했거나, 분석 후 본문·첨부 텍스트가 바뀐 공고."""
        rows = self.db.execute(
            "SELECT uid FROM postings WHERE include=1 AND (analyzed_hash IS NULL OR analyzed_hash != text_hash) "
            "ORDER BY apply_end_on DESC"
        ).fetchall()
        return [r["uid"] for r in rows]

    def save_extraction(self, uid: str, model: str, result_json: str, now: Optional[str] = None) -> None:
        now = now or datetime.now().isoformat(timespec="seconds")
        h = self.db.execute("SELECT text_hash FROM postings WHERE uid=?", (uid,)).fetchone()["text_hash"]
        self.db.execute("INSERT OR REPLACE INTO extractions VALUES (?,?,?,?,?)", (uid, h, model, now, result_json))
        self.db.execute("UPDATE postings SET analyzed_hash=? WHERE uid=?", (h, uid))
        self.db.commit()

    def get_extraction(self, uid: str) -> Optional[dict]:
        row = self.db.execute("SELECT result_json FROM extractions WHERE uid=?", (uid,)).fetchone()
        return json.loads(row["result_json"]) if row else None

    def export(self, institutes: dict[str, dict], include_only: bool = True, with_text: bool = False) -> list[dict]:
        """jobfit `/internships` API 필드에 맞춘 내보내기. with_text=True면 AI 분석용 원문 포함."""
        q = "SELECT * FROM postings" + (" WHERE include=1" if include_only else "") + " ORDER BY apply_end_on DESC"
        out = []
        for row in self.db.execute(q).fetchall():
            inst = institutes.get(row["institute"], {})
            item = {
                "uid": row["uid"],
                "institute": {"code": row["institute"], "name": inst.get("name", row["institute"])},
                "title": row["title"],
                "category": row["category"],
                "fields": inst.get("fields", []),
                "targets": json.loads(row["targets"] or "[]"),
                "region": inst.get("region"),
                "posted_on": row["posted_on"],
                "apply_start_on": row["apply_start_on"],
                "apply_end_on": row["apply_end_on"],
                "is_closed": bool(row["is_closed"]),
                "official_url": row["url"],
                "source_url": row["url"],
                "revision": row["revision"],
                "content_hash": row["content_hash"],
            }
            atts = self.db.execute(
                "SELECT name, skipped_reason, text FROM attachments WHERE uid=?", (row["uid"],)
            ).fetchall()
            item["attachments"] = [
                {"name": a["name"], "skipped_reason": a["skipped_reason"], "text_chars": len(a["text"] or "")}
                for a in atts
            ]
            if with_text:
                item["body_text"] = row["body_text"]
                for a, src in zip(item["attachments"], atts):
                    a["text"] = src["text"]
            out.append(item)
        return out
