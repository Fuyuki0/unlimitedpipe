from unlimitedpipe.sources.ask import terms
from unlimitedpipe.sources.search import matches, split_words, stem, word_pattern
from unlimitedpipe.thai import split


def test_thai_questions_are_split_into_words():
    assert split("ราคาทองวันนี้") == ["ราคา", "ทอง"]  # the gold price today
    assert terms("น้ำท่วมกรุงเทพตอนนี้เป็นอย่างไร") == ["น้ำท่วม", "กรุงเทพ"]
    assert terms("พายุไต้ฝุ่นเข้าญี่ปุ่นไหม") == ["พายุ", "ไต้ฝุ่น", "ญี่ปุ่น"]
    assert terms("Bangkok น้ำท่วม today?") == ["bangkok", "น้ำท่วม"]
    assert split("ศุภมาสลงพื้นที่") == ["ศุภมาสลงพื้นที่"]  # unknown words stay one term


def test_casual_thai_leaves_only_the_topic():
    assert terms("Bitget hack เป็นไงบ้าง") == ["bitget", "hack"]  # how is it going
    assert terms("ขอข่าว Bitget hack หน่อย") == ["bitget", "hack"]  # news please
    assert terms("Bitget hack มีอะไรใหม่") == ["bitget", "hack"]  # anything new
    assert terms("Bitget hack อัปเดต") == ["bitget", "hack"]  # update
    assert split("น้ำท่วมเชียงใหม่") == ["น้ำท่วม", "เชียงใหม่"]  # ใหม่ inside a name stays
    assert split("ปีใหม่") == ["ปีใหม่"]  # New Year


def test_thai_words_match_other_spellings_and_english():
    assert word_pattern("กรุงเทพ").search("น้ำท่วม กทม. หนัก")
    assert word_pattern("น้ำท่วม").search("Bangkok floods worsen")
    assert word_pattern("ทอง").search("ราคาทองคำวันนี้")
    assert not word_pattern("น้ำท่วม").search("Bangkok traffic")


def test_search_splits_thai_words_too():
    assert split_words(["น้ำท่วมกรุงเทพ"]) == ["น้ำท่วม", "กรุงเทพ"]
    assert split_words(["ข่าว"]) == ["ข่าว"]  # nothing left to search: keep what was typed
    item = {"title": "Bangkok declared public disaster zone after flooding"}
    assert matches(item, split_words(["น้ำท่วมกรุงเทพ"]))


def test_english_words_match_their_other_forms():
    assert [stem(w) for w in ("hacks", "companies", "company", "crashes", "news", "status")] == [
        "hack",
        "compan",
        "compan",
        "crash",
        "news",
        "status",
    ]
    assert word_pattern("buys").search("Berkshire bought $136M")
    assert word_pattern("hacked").search("Bitget hack")
    assert not word_pattern("hack").search("Thackeray")
