from app.tier_source import parse_tier_list

SAMPLE_HTML = """
<html><body>
<div><h2>Bug Type</h2></div>
<p>One of the weakest types in Pokemon Go, low priority overall for raids.</p>
<div>Mega Heracross</div>
<div>Shadow Vikavolt</div>
<div>Mega Pinsir</div>
<div><h2>Dark Type</h2></div>
<p>Dark Type has the advantage of dealing Super Effective damage widely.</p>
<div>Mega Absol</div>
<div>Mega Tyranitar</div>
<p>Log in</p>
<p>to comment.</p>
<div>이 밑은 댓글이라 무시돼야 한다</div>
</body></html>
"""


def test_parse_tier_list_splits_by_type_and_maps_korean_names():
    result = parse_tier_list(SAMPLE_HTML)

    assert result["벌레"] == ["Mega Heracross", "Shadow Vikavolt", "Mega Pinsir"]
    assert result["악"] == ["Mega Absol", "Mega Tyranitar"]


def test_parse_tier_list_stops_before_comments():
    result = parse_tier_list(SAMPLE_HTML)
    assert "댓글" not in " ".join(result["악"])


def test_parse_tier_list_raises_without_recognizable_type_headers():
    try:
        parse_tier_list("<html><body><p>no types here</p></body></html>")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")
