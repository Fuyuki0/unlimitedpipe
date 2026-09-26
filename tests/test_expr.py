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
        ("stock - 1 == 2", True),
        ("price - stock == 86", True),
        ("stock * 2 + 1 == 7", True),
        ("(stock + 1) * 2 == 8", True),
        ("price / 2 == 44.5", True),
        ("stock / 0 == null", True),
        ("-stock == -3", True),
        ("stock > -1", True),
        ("missing - 1 == null", True),
        ("name - 1 == null", True),
        ("round(price / 7) == 13", True),
        ("round(price / 7, 2) == 12.71", True),
        ("abs(0 - stock) == 3", True),
        ('short(1400000000) == "1.4B"', True),
        ('commas(84079.6929, 2) == "84,079.69"', True),
        ('commas("1234567") == "1,234,567"', True),
        ('title("the open network") == "The Open Network"', True),
        ('short(7000000) == "7M"', True),
        ('short(-250000) == "-250K"', True),
        ('short(950) == "950"', True),
        ('short(12.5) == "12.5"', True),
        ("short(name) == null", True),
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
    with pytest.raises(ExpressionError, match="known: abs, commas, date, exists"):
        compile_expression("shout(name)")


def test_invalid_regex_is_reported():
    with pytest.raises(ExpressionError, match="regular expression"):
        compile_expression('name matches "("')(EVENT)


def test_function_arity_is_checked():
    with pytest.raises(ExpressionError, match=r"replace\(\) takes 3 argument"):
        compile_expression('replace(name, "a")')
    with pytest.raises(ExpressionError, match=r"lower\(\) takes 1 argument"):
        compile_expression("lower(name, name)")
    with pytest.raises(ExpressionError, match=r"round\(\) takes 1 or 2 argument"):
        compile_expression("round(price, 1, 2)")


def test_empty_expression():
    with pytest.raises(ExpressionError):
        compile_expression("  ")
