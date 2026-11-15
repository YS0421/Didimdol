"""NCS(국가직무능력표준) 분류 데이터 → 출연연 관련 큐레이션 (근거 출처 C).

원본: 공공데이터포털 '학교법인한국기술교육대학교_원격훈련심사센터_NCS(국가직무능력표준)분류_20251125'
      (data.go.kr 파일데이터 15153998, 이용허락범위 제한 없음). 열: 분류 코드, 명칭.
원본 CSV는 엑셀을 거치며 코드 앞자리 0이 빠져 있어 자릿수로 복원한다.

사용:
  python -m didimdol_ai.ncs build      # collector_data/ncs_raw/ncs_classification.csv → data/ncs_curated.json
  python -m didimdol_ai.ncs search 화학물질
"""

from __future__ import annotations

import csv
import io
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .config import DATA_DIR
from .models import Requirement

ROOT = Path(__file__).resolve().parents[1]
RAW_CSV = ROOT / "collector_data" / "ncs_raw" / "ncs_classification.csv"
CURATED = DATA_DIR / "ncs_curated.json"
SOURCE = ("공공데이터포털 '학교법인한국기술교육대학교_원격훈련심사센터_NCS(국가직무능력표준)분류_20251125' "
          "(data.go.kr 15153998, 이용허락범위 제한 없음)")

# 출연연 인턴과 관련 있는 대분류 → 디딤돌 분야 (빈 리스트 = 행정 계열)
MAJOR_FIELDS = {
    "01": [], "02": [], "06": ["chem"], "14": ["infra"], "15": ["mech"], "16": ["material"],
    "17": ["chem"], "19": ["elec"], "20": ["it"], "21": ["chem"], "23": ["energy"],
}
AI_PATTERN = re.compile(r"빅데이터|데이터\s*분석|인공지능|머신러닝|딥러닝|데이터\s*모델|데이터\s*아키텍처")

# 능력단위 이름 → 6축 (휴리스틱; 먼저 걸리는 규칙 하나만 적용, 없으면 domain)
AXIS_RULES = [
    ("data", r"분석|데이터|통계|모델링|시뮬레이션|프로그래밍|코딩|소프트웨어"),
    ("research", r"실험|시험|측정|분석기기|합성|제조|설계|개발|시제품|평가|검사|공정"),
    ("communication", r"보고서|문서|발표|홍보|교육|커뮤니케이션|기술지원"),
    ("problem", r"개선|진단|문제|트러블|불량|고장|대책"),
    ("collaboration", r"계획|관리|운영|일정|조정|협력|품질경영"),
]


def normalize_code(code: str) -> str:
    code = code.strip()
    if "_" in code:
        return code
    return code.zfill(len(code) + 1) if len(code) % 2 else code


def level_of(code: str) -> str:
    if "_" in code:
        return "element" if "." in code.split("_", 1)[1].split("v", 1)[-1] else "unit"
    return {2: "major", 4: "middle", 6: "minor", 8: "detail"}.get(len(code), "unknown")


def _norm_name(s: str) -> str:
    s = re.sub(r"^\s*\d+\s*[.)]\s*", "", s)
    return re.sub(r"[\s⋅·‧ㆍ・∙,]", "", s)


def axis_for_unit(name: str) -> str:
    for axis, pat in AXIS_RULES:
        if re.search(pat, name):
            return axis
    return "domain"


# ---------------------------------------------------------------- 빌드


def build(raw_csv: Path = RAW_CSV, out: Path = CURATED) -> dict:
    rows = list(csv.reader(io.StringIO(raw_csv.read_bytes().decode("cp949"))))[1:]
    names = {normalize_code(c): n.strip() for c, n in rows if c.strip()}
    details = {}
    for code, name in names.items():
        if level_of(code) != "detail" or code[:2] not in MAJOR_FIELDS:
            continue
        path = [names.get(code[:2], ""), names.get(code[:4], ""), names.get(code[:6], ""), name]
        fields = list(MAJOR_FIELDS[code[:2]])
        if AI_PATTERN.search(" ".join(path)) and "ai" not in fields:
            fields.append("ai")
        details[code] = {"name": name, "path": path, "fields": fields, "units": []}
    for code, name in names.items():
        if level_of(code) == "unit" and code[:8] in details:
            details[code[:8]]["units"].append({"code": code, "name": name, "axis": axis_for_unit(name)})
    for d in details.values():
        d["units"].sort(key=lambda u: u["code"])
    data = {"source": SOURCE, "built_from_rows": len(rows), "details": details}
    out.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    return data


# ---------------------------------------------------------------- 조회


@lru_cache(maxsize=None)
def load() -> dict:
    if not CURATED.exists():
        return {"source": SOURCE, "details": {}}
    return json.loads(CURATED.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _name_index() -> dict[str, list[str]]:
    idx: dict[str, list[str]] = {}
    for code, d in load()["details"].items():
        idx.setdefault(_norm_name(d["name"]), []).append(code)
    return idx


def find_detail_codes(role_ncs: Optional[dict]) -> list[str]:
    """추출된 직무기술서 NCS 분류(대·중·소·세분류 이름) → 세분류 코드 목록.

    세분류 칸에 '01.회계‧감사 02.세무'처럼 여러 개가 적힌 경우도 처리한다.
    같은 이름이 여러 대분류에 있으면 대·중분류 이름으로 좁힌다.
    """
    if not role_ncs:
        return []
    detail_text = role_ncs.get("detail") or ""
    parts = [p for p in re.split(r"\s*(?:\d+\s*[.)]|,|/)\s*", detail_text) if p.strip()] or [detail_text]
    major = _norm_name(role_ncs.get("major") or "")
    middle = _norm_name(role_ncs.get("middle") or "")
    minor = _norm_name(role_ncs.get("minor") or "")
    details = load()["details"]

    def same_major(c: str) -> bool:
        return bool(major) and major[:2] in _norm_name(details[c]["path"][0])

    out: list[str] = []
    for part in parts:
        key = _norm_name(part)
        if len(key) < 2:  # '-' 같은 빈 세분류
            continue
        codes = _name_index().get(key, [])
        if not codes:  # 정확히 같은 이름이 없으면 포함 관계로 (같은 대분류에서 하나로 좁혀질 때만)
            partial = [c for name, cs in _name_index().items() if key in name for c in cs]
            partial = [c for c in partial if same_major(c)] or partial
            codes = partial if len(partial) == 1 else []
        if len(codes) > 1:
            narrowed = [c for c in codes if same_major(c)
                        or (middle and middle[:2] in _norm_name(details[c]["path"][1]))]
            codes = narrowed or codes
        out += [c for c in codes if c not in out]
    if not out and minor:  # 세분류가 비었거나 못 찾으면 소분류 아래 세분류들
        out = [c for c, d in details.items() if _norm_name(d["path"][2]) == minor and (not major or same_major(c))]
    return out


def fields_for(codes: list[str]) -> list[str]:
    out: list[str] = []
    for c in codes:
        for f in load()["details"].get(c, {}).get("fields", []):
            if f not in out:
                out.append(f)
    return out


def curated_requirements(code: str, id_prefix: str, limit: int = 8) -> list[Requirement]:
    """세분류의 능력단위 → 기본 요구 항목 (학부 인턴 기준 수준 1 '접함', 출처 ncs_curated)."""
    d = load()["details"].get(code)
    if not d:
        return []
    return [
        Requirement(id=f"{id_prefix}#ncs-{u['code']}", label=u["name"], required_level=1, axes=[u["axis"]],
                    source="ncs_curated", necessity="curated", quote=f"NCS {d['name']} 능력단위 {u['code']}",
                    ncs_unit_code=u["code"], kind="knowledge")
        for u in d["units"][:limit]
    ]


def search(query: str, limit: int = 20) -> list[dict]:
    q = _norm_name(query)
    out = []
    for code, d in load()["details"].items():
        hay = _norm_name(" ".join(d["path"]))
        unit_hit = [u for u in d["units"] if q in _norm_name(u["name"])]
        if q in hay or unit_hit:
            out.append({"code": code, "name": d["name"], "path": d["path"], "fields": d["fields"],
                        "units": len(d["units"]), "matched_units": [u["name"] for u in unit_hit[:5]]})
        if len(out) >= limit:
            break
    return out


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        data = build()
        n_units = sum(len(d["units"]) for d in data["details"].values())
        print(f"원본 {data['built_from_rows']:,}행 → 세분류 {len(data['details'])}개, 능력단위 {n_units:,}개 → {CURATED}")
    elif cmd == "search":
        for r in search(" ".join(sys.argv[2:])):
            print(f"{r['code']} {' > '.join(r['path'])} · 분야 {r['fields']} · 능력단위 {r['units']}개 {r['matched_units']}")
