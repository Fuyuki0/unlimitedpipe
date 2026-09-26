"""Thai words for search and ask.

Thai is written without spaces between words, so a question such as "ราคาทองวันนี้" (the gold
price today) is one run of letters. It is split here with a small dictionary of words common
in news, longest match first; question and time words are dropped, and letters no word matches
stay together as one search term. Each news word also names its common other spellings and its
English equivalent, so a Thai question finds English sources too.
"""

from __future__ import annotations

import re

THAI_RUN = re.compile("[\u0e00-\u0e7f]+")

# Words that only shape the question.
SKIP = frozenset(
    "วันนี้ ตอนนี้ ขณะนี้ เมื่อวาน สัปดาห์นี้ อาทิตย์นี้ เดือนนี้ ล่าสุด "  # noqa: SIM905
    "อย่างไร ยังไง อะไร ไหม มั้ย บ้าง ที่ไหน ไหน เมื่อไร เมื่อไหร่ หรือ "
    "หรือไม่ ครับ ค่ะ คะ จ้า เป็น มี ที่ ของ และ ใน กับ ได้ ให้ จะ ไป มา "
    "แล้ว ยัง ช่วย บอก หน่อย เกี่ยวกับ ข่าว เกิด ขึ้น อยู่ ตอน นี้ ไร ใคร "
    "ทำไม เท่าไร เท่าไหร่ กี่ แค่ไหน มาก ใหญ่ ล่ะ เข้า ออก ช่วง เรื่อง "
    "สถานการณ์ ข้อมูล รายงาน".split()
)

# News words: other spellings and English equivalents to match as well.
WORDS: dict[str, tuple[str, ...]] = {
    "น้ำท่วม": ("ท่วม", "flood"),
    "ท่วม": ("flood",),
    "กรุงเทพ": ("กทม", "กรุงฯ", "bangkok"),
    "กทม": ("กรุงเทพ", "bangkok"),
    "ราคา": ("price",),
    "ทองคำ": ("ทอง", "gold"),
    "ทอง": ("gold",),
    "น้ำมัน": ("oil",),
    "หุ้น": ("stock", "share"),
    "ดอกเบี้ย": ("interest rate", "rate"),
    "เงินเฟ้อ": ("inflation",),
    "ค่าเงิน": ("currency", "baht"),
    "บาท": ("baht",),
    "ดอลลาร์": ("dollar", "usd"),
    "แผ่นดินไหว": ("earthquake", "quake"),
    "พายุ": ("storm", "typhoon", "cyclone"),
    "ไต้ฝุ่น": ("typhoon",),
    "สึนามิ": ("tsunami",),
    "ฝนตก": ("ฝน", "rain"),
    "ฝน": ("rain",),
    "สภาพอากาศ": ("อากาศ", "weather"),
    "อากาศ": ("weather",),
    "อุณหภูมิ": ("temperature", "°c"),
    "ฝุ่น": ("pm2.5", "dust"),
    "ไฟไหม้": ("fire",),
    "ไฟป่า": ("wildfire",),
    "ภัยพิบัติ": ("disaster",),
    "โรคระบาด": ("ระบาด", "outbreak"),
    "ระบาด": ("outbreak",),
    "เลือกตั้ง": ("election",),
    "นายกรัฐมนตรี": ("นายกฯ", "prime minister"),
    "นายก": ("prime minister",),
    "รัฐบาล": ("government",),
    "ศาล": ("court",),
    "ธนาคารแห่งประเทศไทย": ("ธปท", "แบงก์ชาติ", "bank of thailand"),
    "แบงก์ชาติ": ("ธปท", "bank of thailand"),
    "ธนาคาร": ("bank",),
    "คริปโต": ("crypto",),
    "บิตคอยน์": ("bitcoin", "btc"),
    "แฮก": ("hack",),
    "ภูเขาไฟ": ("volcano",),
    "เศรษฐกิจ": ("economy",),
    "ส่งออก": ("export",),
    "ภาษี": ("tax", "tariff"),
    "ไทย": ("thailand", "thai"),
    "ประเทศไทย": ("ไทย", "thailand"),
    "เชียงใหม่": ("chiang mai",),
    "ภูเก็ต": ("phuket",),
    "ขอนแก่น": ("khon kaen",),
    "หาดใหญ่": ("hat yai",),
    "พม่า": ("เมียนมา", "myanmar"),
    "เมียนมา": ("พม่า", "myanmar"),
    "กัมพูชา": ("cambodia",),
    "ลาว": ("laos",),
    "มาเลเซีย": ("malaysia",),
    "จีน": ("china",),
    "ญี่ปุ่น": ("japan",),
    "สหรัฐ": ("อเมริกา", "us", "united states"),
    "อเมริกา": ("สหรัฐ", "us"),
    "รัสเซีย": ("russia",),
    "ยูเครน": ("ukraine",),
    "อินเดีย": ("india",),
    "ยุโรป": ("europe", "eu"),
    "อพยพ": ("evacuat",),
    "เตือน": ("warning", "alert"),
    "รถไฟ": ("train", "rail"),
    "สนามบิน": ("airport",),
    "อุบัติเหตุ": ("accident",),
}
_KNOWN = sorted(set(WORDS) | SKIP, key=len, reverse=True)


def split(text: str) -> list[str]:
    """The search terms in a run of Thai: dictionary words (question words dropped) and the
    runs of letters between them."""
    terms: list[str] = []
    unknown = ""
    i = 0
    while i < len(text):
        # Short words ("มา", "ที่") hide inside longer ones ("ศุภมาส", "พื้นที่"), so they only
        # count where a word starts for sure: at the start or right after a known word.
        word = next(
            (w for w in _KNOWN if text.startswith(w, i) and (len(w) > 3 or not unknown)), None
        )
        if word is None:
            unknown += text[i]
            i += 1
            continue
        if len(unknown) >= 2:
            terms.append(unknown)
        unknown = ""
        if word not in SKIP:
            terms.append(word)
        i += len(word)
    if len(unknown) >= 2:
        terms.append(unknown)
    return terms


def words_in(text: str) -> list[str]:
    """Every Thai run in a text, split into terms."""
    return [term for run in THAI_RUN.findall(text) for term in split(run)]


def forms(word: str) -> tuple[str, ...]:
    """A Thai term and what else to match for it: other spellings, then English words."""
    return (word, *WORDS.get(word, ()))
