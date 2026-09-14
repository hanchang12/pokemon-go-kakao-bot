"""포켓몬 18타입 상성표 (Pokemon GO 기준, 6세대 이후 표준 - 스틸/고스트/악 상성 포함).

공격 시 배율만 예외로 나열한다(그 외는 전부 1배). TYPE_EFFECTIVENESS를 뒤집어
방어 시 약점/저항도 계산한다.
"""

ALL_TYPES = [
    "노말", "불꽃", "물", "풀", "전기", "얼음", "격투", "독", "땅",
    "비행", "에스퍼", "벌레", "바위", "고스트", "드래곤", "악", "강철", "페어리",
]

# attacker -> {defender: multiplier}, 1배는 생략
TYPE_EFFECTIVENESS: dict[str, dict[str, float]] = {
    "노말": {"바위": 0.5, "강철": 0.5, "고스트": 0},
    "불꽃": {"풀": 2, "얼음": 2, "벌레": 2, "강철": 2, "불꽃": 0.5, "물": 0.5, "바위": 0.5, "드래곤": 0.5},
    "물": {"불꽃": 2, "땅": 2, "바위": 2, "물": 0.5, "풀": 0.5, "드래곤": 0.5},
    "전기": {"물": 2, "비행": 2, "전기": 0.5, "풀": 0.5, "드래곤": 0.5, "땅": 0},
    "풀": {"물": 2, "땅": 2, "바위": 2, "불꽃": 0.5, "풀": 0.5, "독": 0.5, "비행": 0.5, "벌레": 0.5, "드래곤": 0.5, "강철": 0.5},
    "얼음": {"풀": 2, "땅": 2, "비행": 2, "드래곤": 2, "불꽃": 0.5, "물": 0.5, "얼음": 0.5, "강철": 0.5},
    "격투": {"노말": 2, "얼음": 2, "바위": 2, "악": 2, "강철": 2, "독": 0.5, "비행": 0.5, "에스퍼": 0.5, "벌레": 0.5, "페어리": 0.5, "고스트": 0},
    "독": {"풀": 2, "페어리": 2, "독": 0.5, "땅": 0.5, "바위": 0.5, "고스트": 0.5, "강철": 0},
    "땅": {"불꽃": 2, "전기": 2, "독": 2, "바위": 2, "강철": 2, "풀": 0.5, "벌레": 0.5, "비행": 0},
    "비행": {"풀": 2, "격투": 2, "벌레": 2, "전기": 0.5, "바위": 0.5, "강철": 0.5},
    "에스퍼": {"격투": 2, "독": 2, "에스퍼": 0.5, "강철": 0.5, "악": 0},
    "벌레": {"풀": 2, "에스퍼": 2, "악": 2, "불꽃": 0.5, "격투": 0.5, "독": 0.5, "비행": 0.5, "고스트": 0.5, "강철": 0.5, "페어리": 0.5},
    "바위": {"불꽃": 2, "얼음": 2, "비행": 2, "벌레": 2, "격투": 0.5, "땅": 0.5, "강철": 0.5},
    "고스트": {"에스퍼": 2, "고스트": 2, "악": 0.5, "노말": 0},
    "드래곤": {"드래곤": 2, "강철": 0.5, "페어리": 0},
    "악": {"에스퍼": 2, "고스트": 2, "격투": 0.5, "악": 0.5, "페어리": 0.5},
    "강철": {"얼음": 2, "바위": 2, "페어리": 2, "불꽃": 0.5, "물": 0.5, "전기": 0.5, "강철": 0.5},
    "페어리": {"격투": 2, "드래곤": 2, "악": 2, "불꽃": 0.5, "독": 0.5, "강철": 0.5},
}


def offense(attacker_type: str) -> tuple[list[str], list[str], list[str]]:
    """(효과 2배로 때리는 타입들, 0.5배로 때리는 타입들, 안 통하는 타입들)"""
    chart = TYPE_EFFECTIVENESS.get(attacker_type, {})
    strong = [t for t, m in chart.items() if m == 2]
    weak = [t for t, m in chart.items() if m == 0.5]
    immune = [t for t, m in chart.items() if m == 0]
    return strong, weak, immune


def defense(target_type: str) -> tuple[list[str], list[str], list[str]]:
    """(이 타입이 2배로 맞는 공격 타입들, 0.5배로 맞는 타입들, 안 맞는 타입들)"""
    weak_to: list[str] = []
    resists: list[str] = []
    immune_to: list[str] = []
    for attacker, chart in TYPE_EFFECTIVENESS.items():
        multiplier = chart.get(target_type, 1)
        if multiplier == 2:
            weak_to.append(attacker)
        elif multiplier == 0.5:
            resists.append(attacker)
        elif multiplier == 0:
            immune_to.append(attacker)
    return weak_to, resists, immune_to


def format_matchup(type_name: str) -> str | None:
    if type_name not in TYPE_EFFECTIVENESS:
        return None

    strong, weak, immune = offense(type_name)
    weak_to, resists, immune_to = defense(type_name)

    lines = [f"⚔️ {type_name} 타입 상성"]
    if strong:
        lines.append("🔺 공격 시 2배: " + ", ".join(strong))
    if weak:
        lines.append("🔻 공격 시 0.5배: " + ", ".join(weak))
    if immune:
        lines.append("🚫 공격해도 안 통함: " + ", ".join(immune))
    if weak_to:
        lines.append("⚠️ 이 타입의 약점(2배로 맞음): " + ", ".join(weak_to))
    if resists:
        lines.append("🛡️ 이 타입이 저항(0.5배로 맞음): " + ", ".join(resists))
    if immune_to:
        lines.append("✨ 이 타입은 안 맞음: " + ", ".join(immune_to))
    return "\n".join(lines)
