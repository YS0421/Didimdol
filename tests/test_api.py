"""API 서버 테스트: 임시 공고 DB + 가짜 Claude 클라이언트 (실제 API 호출 없음)."""

import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from didimdol_ai import api
from didimdol_ai.collector.filters import classify
from didimdol_ai.collector.models import Attachment, Posting, PostingRef
from didimdol_ai.collector.store import Store

KEY = "test-key-123"
ROLES = [{
    "role_name": "세포 실험 연구 보조", "category": "research", "fields": ["chem"], "duties": ["세포 실험"],
    "eligibility": {"undergrad_eligible": True, "targets": ["expected", "graduated"], "notes": ""}, "ncs": None,
    "requirements": [
        {"label": "세포 및 동물실험 경험", "kind": "skill", "necessity": "preferred", "required_level": 2,
         "axes": ["research"], "quote": "세포 및 동물실험 유경험자"},
        {"label": "실험 결과 분석", "kind": "skill", "necessity": "required", "required_level": 2,
         "axes": ["research", "data"], "quote": "실험 결과 분석 능력"},
    ]}]
CARD = {"id": "c1", "kind": "학부연구생", "title": "세포 독성 실험 보조",
        "actions": "프로토콜대로 세포를 배양하고 MTT assay로 측정했다.", "tools": ["MTT assay"]}


class FakeLLM:
    """judge/feedback/draft 요청을 구분해 그럴듯한 JSON을 돌려준다."""

    def __init__(self):
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        props = kw["output_config"]["format"]["schema"]["properties"]
        if "evidence" in props:
            out = {"evidence": [{"requirement_id": props["evidence"]["items"]["properties"]["requirement_id"]["enum"][0],
                                 "level": 2, "quote": "세포를 배양하고", "reason": "직접 수행"}], "followup_questions": []}
        elif "messages" in props:
            n = len(json.loads(kw["messages"][0]["content"])["items"])
            out = {"messages": [{"index": i, "text": "이번 주도 한 칸 나아갔어요."} for i in range(n)], "healing_text": ""}
        else:
            out = {"cards": [{"kind": "학부연구생", "title": "세포 실험", "period": "", "role": "",
                              "actions": "세포 배양과 MTT assay를 수행했다.", "tools": ["MTT assay"], "outcome": "",
                              "learned": "", "source_quote": "세포 배양과 MTT assay를 수행", "questions": []}]}
        return SimpleNamespace(stop_reason="end_turn", model=kw["model"],
                               content=[SimpleNamespace(type="text", text=json.dumps(out, ensure_ascii=False))],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        db = Path(cls.tmp.name) / "p.sqlite3"
        s = Store(str(db))
        p = Posting(PostingRef("kiom", "1", "하반기 인턴 채용", "https://example.org/1",
                               apply_end_on=date(2099, 1, 1)))
        p.attachments = [Attachment("a.pdf", "u", text="학사학위 소지자 " * 30)]
        classify(p)
        s.upsert(p)
        s.save_extraction("kiom:1", "fake", json.dumps({"uid": "kiom:1", "model": "fake", "roles": ROLES, "dropped": []},
                                                       ensure_ascii=False))
        s.close()
        api.DB_PATH = db
        api._client = FakeLLM()
        os.environ["DIDIMDOL_API_KEY"] = KEY
        cls.c = TestClient(api.app)
        cls.h = {"X-Didimdol-Key": KEY}

    @classmethod
    def tearDownClass(cls):
        api._client = None
        os.environ.pop("DIDIMDOL_API_KEY", None)
        cls.tmp.cleanup()

    def test_auth(self):
        self.assertEqual(self.c.get("/health").status_code, 200)
        self.assertEqual(self.c.get("/v1/postings").status_code, 401)
        self.assertEqual(self.c.get("/v1/postings", headers={"X-Didimdol-Key": "wrong"}).status_code, 401)

    def test_postings_and_roles(self):
        items = self.c.get("/v1/postings", headers=self.h).json()
        self.assertEqual(items[0]["uid"], "kiom:1")
        self.assertTrue(items[0]["analyzed"])
        roles = self.c.get("/v1/postings/kiom:1/roles", headers=self.h).json()["roles"]
        self.assertEqual(roles[0]["role_name"], "세포 실험 연구 보조")
        self.assertEqual(self.c.get("/v1/postings/none:0/roles", headers=self.h).status_code, 404)

    def test_recommendations(self):
        body = {"profile": {"status": "expected", "interest_fields": ["chem"]}, "cards": [CARD]}
        r = self.c.post("/v1/recommendations", json=body, headers=self.h).json()
        self.assertEqual(r["items"][0]["role_name"], "세포 실험 연구 보조")
        self.assertTrue(r["items"][0]["matches"])

    def test_judge(self):
        r = self.c.post("/v1/judge", json={"uid": "kiom:1", "role_index": 0, "card": CARD}, headers=self.h).json()
        self.assertEqual(r["evidences"][0]["level"], 2)
        self.assertEqual(self.c.post("/v1/judge", json={"uid": "kiom:1", "role_index": 5, "card": CARD},
                                     headers=self.h).status_code, 404)

    def _report_body(self, **kw):
        ev = [{"requirement_id": "kiom:1#0-0", "level": 2, "card_id": "c1", "quote": "세포를 배양하고"}]
        body = {"goal": {"uid": "kiom:1", "role_index": 0, "weeks_left": 6, "weekly_hours": 6},
                "history": [{"checkin": {"week": "W1", "self_ratings": {"research": 3}}, "evidences": []},
                            {"checkin": {"week": "W2", "self_ratings": {"research": 4}, "condition": 4},
                             "evidences": ev}],
                "cards": [CARD]}
        body.update(kw)
        return body

    def test_report_json_and_html(self):
        r = self.c.post("/v1/report", json=self._report_body(kind="monthly"), headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("axes", data)
        self.assertEqual(data["series"]["weeks"], ["W1", "W2"])
        html = self.c.post("/v1/report", json=self._report_body(format="html"), headers=self.h)
        self.assertIn("text/html", html.headers["content-type"])
        self.assertIn("육각형 능력치", html.text)
        frag = self.c.post("/v1/report", json=self._report_body(format="html_fragment"), headers=self.h)
        self.assertTrue(frag.text.startswith("<style>"))  # 사이트에 끼워 넣는 조각 (html/body 없음)
        self.assertNotIn("<html", frag.text)

    def test_report_with_feedback(self):
        data = self.c.post("/v1/report", json=self._report_body(with_feedback=True, coach_tone="direct"),
                           headers=self.h).json()
        self.assertTrue(data["feedback"])
        self.assertEqual(data["feedback"][0]["source"], "llm")

    def test_report_validation(self):
        bad = self._report_body(history=[])
        self.assertEqual(self.c.post("/v1/report", json=bad, headers=self.h).status_code, 422)

    def test_ncs_endpoints(self):
        r = self.c.get("/v1/ncs/search", params={"q": "화학물질"}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertIn("data.go.kr", r.json()["source"])
        if r.json()["items"]:  # data/ncs_curated.json이 빌드돼 있으면 상세도 확인
            code = r.json()["items"][0]["code"]
            self.assertEqual(self.c.get(f"/v1/ncs/{code}", headers=self.h).json()["code"], code)
        self.assertEqual(self.c.get("/v1/ncs/search", params={"q": "a"}, headers=self.h).status_code, 422)
        self.assertEqual(self.c.get("/v1/ncs/00000000", headers=self.h).status_code, 404)

    def test_self_status_form(self):
        body = {"week": "W2", "profile": {"status": "expected"}, "goal": {"uid": "kiom:1", "role_index": 0, "weeks_left": 6},
                "milestones": [{"milestone_id": "m1", "title": "실험 결과 분석 연습"}], "cards": [CARD],
                "endpoints": {"checkin": "/api/modules/sirsoft-jobfit/me/jobfit/checkins"}}
        r = self.c.post("/v1/forms/self-status", json=body, headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertIn('class="dd-input"', r.text)
        self.assertIn("세포 실험 연구 보조", r.text)  # 목표 직무 선택지를 공고 DB에서 채움
        self.assertEqual(self.c.post("/v1/forms/self-status", json=body).status_code, 401)

    def test_card_draft_upload(self):
        text = "학부연구생 활동: 세포 배양과 MTT assay를 수행하고 결과를 정리했다. " * 3
        r = self.c.post("/v1/cards/draft", headers=self.h,
                        files={"file": ("portfolio.txt", text.encode("utf-8"), "text/plain")})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(r.json()["drafts"]), 1)
        bad = self.c.post("/v1/cards/draft", headers=self.h, files={"file": ("x.exe", b"MZ", "application/octet-stream")})
        self.assertEqual(bad.status_code, 415)


if __name__ == "__main__":
    unittest.main()
