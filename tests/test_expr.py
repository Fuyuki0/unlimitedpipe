import pytest

from unlimitedpipe.errors import ExpressionError
from unlimitedpipe.event import Event
from unlimitedpipe.expr import compile_expression

EVENT = Event(
    source="web",
    source_url="https://store.example/p",
    data={
        "name": "Trail Shoe",
        "price": "89.00",
        "stock": 3,
        "availability": "InStock",
        "tags": ["Running", "sale"],
        "country": "Thailand",
        "og:title": "Trail",
        "empty": "",
    },
)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("price > 50", True),
        ("price < 50", False),
        ("price == 89", True),
        ("stock >= 3 and stock <= 3", True),
        ('availability == "InStock"', True),
        ('availability == "instock"', False),
        ('name contains "trail"', True),
        ('tags contains "running"', True),
        ('country in ["Thailand", "Vietnam"]', True),
        ('name startswith "trail"', True),
        ('name endswith "SHOE"', True),
        ('name matches "^Tr.il"', True),
        ("missing > 1", False),
        ("missing == null", True),
        ("not missing", True),
        ("exists(price) and not exists(missing)", True),
        ("empty", False),
        ("exists(empty)", True),
        ('lower(name) == "trail shoe"', True),
        ('number("$1,299.00") > 1000', True),
        ("len(tags) == 2", True),
        ('`og:title` == "Trail"', True),
        ('source_url contains "store"', True),
        ("price > 100 or stock > 1 and stock < 5", True),
        ("(price > 100 or stock > 1) and stock > 5", False),
        ("! (price > 100)", True),
        ('name + "!" == "Trail Shoe!"', True),
        ("stock + 2 == 5", True),
        ('"https://x/" + country == "https://x/Thailand"', True),
        ("missing + 1 == null", True),
        ('replace(name, "Trail ", "") == "Shoe"', True),
        ('replace(missing, "a", "b") == null', True),
        ('date(1790500655624) == "2026-09-27T09:17:35Z"', True),
        ('date("Sun, 20 Sep 2026 09:17:35 GMT") == "2026-09-20T09:17:35Z"', True),
        ("date(name) == null", True),
    ],
)
def test_expressions(expression, expected):
    assert bool(compile_expression(expression)(EVENT)) is expected


def test_parse_error_points_at_the_problem():
    with pytest.raises(ExpressionError) as info:
        compile_expression("price >> 100")
    message = info.value.message
    assert "price >> 100" in message
    assert message.splitlines()[-1].strip() == "^"


def test_unknown_function_lists_known_ones():
    with pytest.raises(ExpressionError, match="known: date, exists"):
        compile_expression("shout(name)")


def test_invalid_regex_is_reported():
    with pytest.raises(ExpressionError, match="regular expression"):
        compile_expression('name matches "("')(EVENT)


def test_function_arity_is_checked():
    with pytest.raises(ExpressionError, match=r"replace\(\) takes 3 argument"):
        compile_expression('replace(name, "a")')
    with pytest.raises(ExpressionError, match=r"lower\(\) takes 1 argument"):
        compile_expression("lower(name, name)")


def test_empty_expression():
    with pytest.raises(ExpressionError):
        compile_expression("  ")
