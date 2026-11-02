import hashlib
import re


def content_tags(text: str) -> list[str]:
    rules = {
        "恐怖": ("鬼", "惊吓", "恐怖", "灵异", "haunted", "horror"),
        "暴力": ("谋杀", "投毒", "刺伤", "murder", "poisoned", "stabbing"),
        "血腥": ("血腥", "肢解", "尸块", "开膛", "gore", "dismember"),
        "性内容": ("性侵", "性暴力", "露骨性描写", "sexual assault"),
        "毒品": ("毒品", "吸毒", "海洛因", "cocaine", "heroin"),
        "自伤": ("自杀", "自残", "自伤", "suicide", "self-harm"),
    }
    lowered = text.lower()
    return [label for label, phrases in rules.items() if any(phrase in lowered for phrase in phrases)]


def suggested_rating(tags: list[str]) -> str:
    if any(tag in tags for tag in ("血腥", "性内容", "毒品", "自伤")):
        return "18+"
    if any(tag in tags for tag in ("恐怖", "暴力")):
        return "16+"
    return "all"


def pii_hits(text: str) -> list[str]:
    patterns = {
        "phone": r"(?<!\d)1[3-9]\d{9}(?!\d)",
        "national_id": r"(?<![\dXx])\d{17}[\dXx](?![\dXx])",
        "email": r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "address": r"(?:省|市|区|县).{2,30}(?:路|街|巷)\d{1,5}号",
        "labeled_name": r"(?:真实姓名|联系人|身份证姓名)[:：]\s*[\u4e00-\u9fff]{2,4}",
    }
    return [kind for kind, pattern in patterns.items()
            if re.search(pattern, text, flags=re.IGNORECASE)]


def simhash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", normalized)
    shingles = [" ".join(tokens[index:index + 4]) for index in range(max(0, len(tokens) - 3))]
    vector = [0] * 64
    for shingle in set(shingles):
        bits = int.from_bytes(hashlib.blake2b(shingle.encode(), digest_size=8).digest(), "big")
        for index in range(64):
            vector[index] += 1 if bits & (1 << index) else -1
    return f"{sum(1 << index for index, weight in enumerate(vector) if weight > 0):016x}"


def fingerprint_match(first: str, second: str, max_distance: int = 3) -> bool:
    return (int(first, 16) ^ int(second, 16)).bit_count() <= max_distance
