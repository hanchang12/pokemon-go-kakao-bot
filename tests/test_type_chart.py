from app.type_chart import ALL_TYPES, TYPE_EFFECTIVENESS, defense, format_matchup, offense


def test_all_types_have_a_chart_entry():
    assert set(TYPE_EFFECTIVENESS.keys()) == set(ALL_TYPES)


def test_fire_offense_is_super_effective_against_grass_and_weak_against_water():
    strong, weak, immune = offense("불꽃")
    assert "풀" in strong
    assert "물" in weak
    assert immune == []


def test_ground_is_immune_to_electric_offense():
    # 땅 타입을 공격할 때 전기 기술은 안 통해야 한다(0배)
    _, _, immune = defense("땅")
    assert "전기" in immune


def test_format_matchup_unknown_type_returns_none():
    assert format_matchup("존재하지않는타입") is None


def test_format_matchup_known_type_lists_all_sections():
    text = format_matchup("드래곤")
    assert text is not None
    assert "드래곤 타입 상성" in text
    assert "약점" in text
