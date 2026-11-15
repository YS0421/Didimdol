"""Claude API 연동 테스트 (실제 API를 호출하지 않는 가짜 클라이언트 사용)."""

import json
import os
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace

from didimdol_ai.collector.filters import classify
from didimdol_ai.collector.models import Attachment, Posting, PostingRef
from didimdol_ai.collector.store import Store
from didimdol_ai.llm.client import load_dotenv
from didimdol_ai.llm.requirements import (
    ExtractionError,
    _schema,
    extract_requirements,
    quote_in_source,
)
from didimdol_ai.scoring import axis_profile
from didimdol_ai.models import Goal

POSTING = {
    "uid": "kiom:1",
    "title": "2026년 하반기 인턴 채용 공고",
    "institute": {"code": "kiom", "name": "한국한의학연구원"},
    "body_text": "",
    "attachments": [{"name": "직무기술서.pdf", "text":
        "자격요건자격요건 학사 학위 취득 후 5년 이내인 자\n"
        "우대사항 ○ Python 등을 활용한 데이터 분석 가능자\n"
        "필요능력 ○ 문서작업능력, 의사소통 능력\n"
        "수행 예정 직무 ○ 한의약 실험 데이터 정리 및 통계 분석 보조 ○ 연구 결과 보고서 작성 보조 "
        "○ 실험실 시료 관리 및 기록 ○ 연구과제 회의 자료 준비\n"
        "직무수행 태도 ○ 연구 데이터를 정확하게 기록하고 관리하려는 태도 ○ 동료 연구원과 협조하는 태도"}],
}

MODEL_OUTPUT = {"roles": [{
    "role_name": "데이터 분석 인턴", "category": "research", "fields": ["ai"],
    "duties": ["실험 데이터 정리"],
    "eligibility": {"undergrad_eligible": True, "targets": ["graduated"], "notes": "학사 취득 후 5년 이내"},
    "ncs": None,
    "requirements": [
        {"label": "Python 데이터 분석", "kind": "skill", "necessity": "preferred", "required_level": 2,
         "axes": ["data"], "quote": "Python 등을 활용한 데이터 분석 가능자"},
        {"label": "문서작업", "kind": "skill", "necessity": "required", "required_level": 1,
         "axes": ["communication"], "quote": "문서작업능력, 의사소통 능력"},
        {"label": "지어낸 항목", "kind": "tool", "necessity": "required", "required_level": 2,
         "axes": ["research"], "quote": "MATLAB 시뮬레이션 경험 필수"},
    ]}]}


class FakeClient:
    def __init__(self, stop_reason="end_turn", output=MODEL_OUTPUT):
        self.calls = []
        self.stop_reason = stop_reason
        self.output = output
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create, stream=self._stream))

    def _stream(self, **kwargs):
        message = self._create(**kwargs)

        class _Ctx:
            def __enter__(self_inner):
                return SimpleNamespace(get_final_message=lambda: message)

            def __exit__(self_inner, *exc):
                return False

        return _Ctx()

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            stop_details=SimpleNamespace(category="cyber") if self.stop_reason == "refusal" else None,
            content=[SimpleNamespace(type="thinking", thinking=""),
                     SimpleNamespace(type="text", text=json.dumps(self.output, ensure_ascii=False))],
            usage=SimpleNamespace(input_tokens=1200, output_tokens=300),
            model=kwargs["model"],
        )


class RequestShapeTest(unittest.TestCase):
    def test_request_uses_structured_output_and_fallback(self):
        client = FakeClient()
        extract_requirements(client, POSTING)
        call = client.calls[0]
        from didimdol_ai.llm.client import DEFAULT_MODEL, model_name
        self.assertEqual(call["model"], model_name())  # .env 설정을 따른다
        saved = os.environ.pop("DIDIMDOL_LLM_MODEL", None)
        try:
            self.assertEqual(model_name(), DEFAULT_MODEL)  # 설정이 없으면 기본 모델
        finally:
            if saved is not None:
                os.environ["DIDIMDOL_LLM_MODEL"] = saved
        self.assertEqual(call["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", call["betas"])
        self.assertEqual(call["output_config"]["format"]["type"], "json_schema")
        self.assertNotIn("thinking", call)  # Opus 5.5는 thinking 비활성화 불가 → 파라미터 생략
        self.assertIn("Python 등을 활용한", call["messages"][0]["content"])

    def test_schema_is_strict(self):
        s = _schema()
        self.assertFalse(s["additionalProperties"])
        req = s["properties"]["roles"]["items"]["properties"]["requirements"]["items"]
        self.assertFalse(req["additionalProperties"])
        self.assertEqual(req["properties"]["axes"]["items"]["enum"],
                         ["domain", "research", "data", "problem", "communication", "collaboration"])


class VerifyTest(unittest.TestCase):
    def test_hallucinated_quote_is_dropped(self):
        ext = extract_requirements(FakeClient(), POSTING)
        labels = [r["label"] for r in ext.roles[0]["requirements"]]
        self.assertEqual(labels, ["Python 데이터 분석", "문서작업"])
        self.assertEqual([d["label"] for d in ext.dropped], ["지어낸 항목"])
        self.assertEqual(ext.usage["input_tokens"], 1200)

    def test_quote_matching_tolerates_spacing_and_pdf_doubling(self):
        src = "자격요건자격요건 학사 학위\n취득 후 5년 이내인 자"
        self.assertTrue(quote_in_source("학사 학위 취득 후 5년", src))
        self.assertTrue(quote_in_source("자격요건 학사 학위", src))
        self.assertFalse(quote_in_source("석사 학위 소지자", src))
        self.assertFalse(quote_in_source("자", src))  # 너무 짧은 인용은 근거로 인정 안 함
        self.assertTrue(quote_in_source("기획력", "필요역량 ○ 기획력, 분석력"))  # 3글자 실제 인용은 인정

    def test_feeds_scoring(self):
        ext = extract_requirements(FakeClient(), POSTING)
        goal = Goal("g", "목표 공고", ext.to_requirements(0), weeks_left=8, weekly_hours=8)
        prof = axis_profile(goal, [])
        self.assertEqual(prof["data"].target, 3.67)  # 수준 2 → 1~5 척도 3.67
        self.assertEqual(goal.requirements[0].source, "posting")


class EligibilityRuleTest(unittest.TestCase):
    def test_common_not_enrolled_clause_applies_to_all_roles(self):
        from didimdol_ai.llm.requirements import apply_eligibility_rules
        roles = [{"eligibility": {"targets": ["enrolled", "expected", "graduated"], "notes": "학력무관"}}]
        src = "공통사항 ▪임용예정일 기준 학위 취득 후 5년 이내인 자로서 재학 또는 휴학 중이 아닌 자"
        [r] = apply_eligibility_rules(roles, src)
        self.assertEqual(r["eligibility"]["targets"], ["expected", "graduated"])
        self.assertIn("규칙 보정", r["eligibility"]["notes"])
        # 그런 문구가 없으면 그대로
        [r] = apply_eligibility_rules(roles, "학부 재학생 지원 가능")
        self.assertIn("enrolled", r["eligibility"]["targets"])


class FailureTest(unittest.TestCase):
    def test_refusal_raises(self):
        with self.assertRaises(ExtractionError):
            extract_requirements(FakeClient(stop_reason="refusal"), POSTING)

    def test_truncated_raises(self):
        with self.assertRaises(ExtractionError):
            extract_requirements(FakeClient(stop_reason="max_tokens"), POSTING)

    def test_title_only_posting_is_skipped_without_api_call(self):
        client = FakeClient()
        with self.assertRaises(ExtractionError):
            extract_requirements(client, {**POSTING, "attachments": []})
        self.assertEqual(client.calls, [])

    def test_too_long_input_is_not_truncated(self):
        big = {**POSTING, "attachments": [{"name": "a.pdf", "text": "가" * 250_000}]}
        client = FakeClient()
        with self.assertRaises(ExtractionError):
            extract_requirements(client, big)
        self.assertEqual(client.calls, [])


class DotenvTest(unittest.TestCase):
    def test_loads_without_overriding(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("# 주석\nDIDIMDOL_TEST_A='a-value'\nDIDIMDOL_TEST_B=b\n")
            os.environ["DIDIMDOL_TEST_B"] = "already"
            try:
                from pathlib import Path
                load_dotenv(Path(path))
                self.assertEqual(os.environ["DIDIMDOL_TEST_A"], "a-value")
                self.assertEqual(os.environ["DIDIMDOL_TEST_B"], "already")
            finally:
                os.environ.pop("DIDIMDOL_TEST_A", None)
                os.environ.pop("DIDIMDOL_TEST_B", None)


class StoreExtractionTest(unittest.TestCase):
    def test_pending_until_saved_and_again_after_change(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "t.sqlite3"))
            p = Posting(PostingRef("kiom", "1", "인턴 채용", "u", apply_end_on=date(2026, 11, 17)))
            p.attachments = [Attachment("a.pdf", "u", text="학사학위 소지자")]
            classify(p)
            store.upsert(p)
            self.assertEqual(store.pending_analysis(), ["kiom:1"])
            store.save_extraction("kiom:1", "claude-opus-5-5", json.dumps({"roles": [], "dropped": []}))
            self.assertEqual(store.pending_analysis(), [])
            p.ref.apply_end_on = date(2026, 11, 20)  # 마감일만 바뀜 → 재분석 불필요
            self.assertEqual(store.upsert(p), "changed")
            self.assertEqual(store.pending_analysis(), [])
            p.attachments[0].text += " (정정)"
            store.upsert(p)
            self.assertEqual(store.pending_analysis(), ["kiom:1"])  # 본문 정정 → 재분석 대상
            store.close()


if __name__ == "__main__":
    unittest.main()
