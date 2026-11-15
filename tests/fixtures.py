"""테스트용 가상 목표: '에너지 소재 분야 연구 인턴' (실제 공고·NCS 코드 아님)."""

from didimdol_ai.models import Evidence, Goal, Requirement


def energy_goal(weeks_left: int = 8, weekly_hours: float = 8) -> Goal:
    # 남은 갭 비용: r2 1→2 (20h) + r3 0→2 (28h) + r4 0→1 (8h) = 56h, 기본 가용 64h
    reqs = [
        Requirement("r1", "Python 데이터 분석", 2, ["data"], "posting", "required",
                    quote="Python 등을 활용한 데이터 분석 가능자", style="analyze"),
        Requirement("r2", "전기화학 실험", 2, ["research", "domain"], "posting", "preferred",
                    quote="전기화학 실험 경험자 우대", style="make"),
        Requirement("r3", "결과 보고서 작성", 2, ["communication"], "ncs_curated"),
        Requirement("r4", "재료 물성 기초 지식", 1, ["domain"], "ncs_curated"),
        Requirement("r5", "연구실 안전교육 이수", 1, [], "posting", "required",
                    quote="연구실 안전교육 이수자"),
    ]
    return Goal("g1", "에너지 소재 연구 인턴", reqs, weeks_left, weekly_hours)


def energy_evidence() -> list[Evidence]:
    return [
        Evidence("r1", 2, "c1", "측정 데이터를 Python으로 정리하고 그래프를 그렸다"),
        Evidence("r2", 1, "c2", "전기화학 수업에서 CV 원리를 배웠다"),
    ]
