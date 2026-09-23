import pytest

from unlimitedpipe import Operator, Output, Source, arg, opt
from unlimitedpipe.component import kind_of


def test_kind_comes_from_the_base_class_even_with_a_kind_option():
    class Stories(Source):
        name = "stories"
        kind: str = opt("Kind of post", default="story")

    assert kind_of(Stories) == kind_of(Stories()) == "source"
    assert Stories().kind == "story"


def test_reserved_option_names_fail_at_definition():
    with pytest.raises(TypeError, match="'version' is reserved"):

        class Bad(Operator):
            name = "bad"
            version: str = opt("API version", default="v2")


def test_options_become_typed_params_with_defaults():
    class Hook(Output):
        """Send events somewhere.

        Longer description.
        """

        name = "hook"
        url: str = arg("Where to send")
        retries: int = opt("Retries", default=3, short="-r")
        headers: list[str] = opt("Extra headers")
        token: str | None = opt("API token", default=None, secret=True)
        dry_run: bool = opt("Do not send")

    params = {p.name: p for p in Hook.params()}
    assert params["url"].positional and params["url"].required
    assert params["retries"].default == 3 and params["retries"].short == "-r"
    assert params["headers"].is_list and params["headers"].default == []
    assert params["token"].optional and params["token"].secret
    assert params["dry_run"].base is bool and params["dry_run"].default is False
    assert Hook.help_summary == "Send events somewhere."
    hook = Hook.from_options({"url": "https://x", "retries": "5", "headers": "A: b", "token": "s"})
    assert (hook.retries, hook.headers) == (5, ["A: b"])
    assert "token" not in str(hook.provenance_step())
