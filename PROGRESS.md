# 개발 진행 기록

기능별 자세한 설명은 [README.md](README.md)에 있어요. 이 문서는 무엇을 어떤 순서로 만들었는지 정리한 기록이에요.

## 완료 (2026-11)

| # | 내용 | 주요 파일 |
|---|---|---|
| 1 | 6축 육각형, 근거 수준, 갭 우선순위, 2×2 방향 계산 | `scoring.py`, `data/axes.json`, `data/planning.json` |
| 2 | 주간 피드백 규칙 엔진: 칭찬·격려·채찍질. 컨디션이 낮으면 채찍질을 억제해요 | `feedback.py` |
| 3 | 공고 수집기: 기관별 어댑터, robots.txt 준수, HWP·HWPX·PDF·DOCX·ZIP 추출 | `collector/` |
| 4 | Claude 연동: 공고 요구 항목 추출(원문 인용 검증), 경험 카드 판정, 피드백 문장, 포트폴리오 → 카드 초안 | `llm/` |
| 5 | 공고 추천(지금 도전 / 준비하며 목표 / 자격 갖춘 뒤 목표)과 다음 한 칸 행동 템플릿 | `recommend.py`, `actions.py` |
| 6 | 리포트 지표 12종과 HTML 리포트(다크 모드, 표 보기) | `metrics.py`, `report_html.py` |
| 7 | G7 연동용 API 서버 (FastAPI, `X-Didimdol-Key` 인증) | `api.py` |
| 8 | 정기 실행 스크립트(수집 → 새 공고만 추출 → 내보내기). 텍스트 해시가 바뀔 때만 다시 분석해요 | `scripts/daily.py` |
| 9 | 검증: 가상 학생 5명 × 8주 시뮬레이션(원칙 위반 0건) | `simulate.py` |
| 10 | NCS 분류 큐레이션(세분류 534개, 능력단위 5,272개)과 직무기술서 NCS 코드 연결 | `ncs.py`, `data/ncs_curated.json` |
| 11 | 항목 나누기 기준을 바꾼 뒤 기존 공고 11건 재추출: 요구 항목 509개 → 1,169개, 인용 실패 0건 | — |
| 12 | 추천 보정: 직업기초능력은 추천 점수에서 빼고, 태도 항목은 어휘 추정을 하지 않고, 낱말 경계를 넘는 우연한 겹침을 막았어요 | `recommend.py` |
| 13 | 수집 기관 확대 5곳 → 13곳: KRISS, KFE, KIGAM, KAERI, KIMM, KIMS, KRRI, KFRI. 마감일 보완, 조회수 제거, 석박사후 공고 제외도 함께 했어요 | `collector/adapters/`, `filters.py`, `runner.py` |
| 14 | Claude OCR: 스캔 PDF와 이미지를 받아 적어 카드 초안을 만들어요 | `llm/ocr.py` |
| 15 | 가상 학부생 예시 데이터셋 (5명 × 8주, API 요청 형식) | `scripts/make_examples.py`, `data/examples/` |
| 16 | 직업기초능력 가중치 0.4, 요건 없는 직무의 준비도 대체값 0.35 | `data/planning.json` |
| 17 | 새 기관 공고 13건 추출: 분석 공고 24건, 직무 346개, 요구 항목 1,755개, 인용 실패 0건 | — |
| 18 | 리포트 화면을 사이트 디자인에 맞게 재설계: 정보 위계 정리, 접힌 상세, 쉬운 말, 조사 자동 선택. 사이트에 끼워 넣는 조각(`html_fragment`) 추가 | `report_html.py`, `text.py` |
| 19 | 자기상태표 입력 화면(체크인·경험 카드·목표/기본 정보)을 사이트에 끼워 넣는 조각으로 구현. `/v1/forms/self-status`, `didimdol:save` 이벤트 | `input_html.py` |

## 남은 일

- **사람이 할 일:** 6축 문구와 행동 템플릿 멘토 검수, 사용성 테스트, G7 jobfit 화면 개발, 공고 추출 결과 검수
- **NCS 능력단위 상세(수준, 정의):** 공공데이터포털 공통 NCS 정보 API의 인증키가 필요해요.
- **기관 확대:** `data/institutes.json`의 `pending` 9곳을 확인하고, 수집이 금지된 기관은 잡알리오 교차 수집으로 보완해요.
