import pytest

from unlimitedpipe.sources.evm import Evm, address_of, text_of, utilization, word


def test_abi_values_are_read():
    symbol = (
        "0x0000000000000000000000000000000000000000000000000000000000000020"
        "0000000000000000000000000000000000000000000000000000000000000004"
        "5553445400000000000000000000000000000000000000000000000000000000"
    )
    assert text_of(symbol) == "USDT"
    assert text_of("0x4d4b520000000000000000000000000000000000000000000000000000000000") == "MKR"
    topic = "0x000000000000000000000000a0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
    assert address_of(topic) == "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
    assert word("0x" + "0" * 63 + "f" + "0" * 63 + "a", 1) == 10


def test_utilization_is_borrowed_over_supplied():
    words = [0, 0, 1000, 0, 936, int(0.0369e27), int(0.0438e27)] + [0] * 5
    market = utilization("0x" + "".join(f"{w:064x}" for w in words))
    assert market["utilization"] == pytest.approx(0.936)
    assert market["borrow_rate"] == pytest.approx(0.0438)


def test_options_are_checked():
    with pytest.raises(ValueError):
        Evm(resource="new-pools", chain="base")
    with pytest.raises(ValueError):
        Evm(resource="aave", min_utilization=90)
    assert Evm(resource="transfers")._min == 25_000_000
