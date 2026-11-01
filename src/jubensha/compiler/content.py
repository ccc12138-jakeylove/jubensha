def content_tags(text: str) -> list[str]:
    rules = {
        "恐怖": ("鬼", "惊吓", "恐怖", "灵异"),
        "血腥": ("血腥", "肢解", "尸块", "开膛"),
        "性内容": ("性侵", "性暴力", "露骨性描写"),
        "自伤": ("自杀", "自残", "自伤"),
    }
    return [label for label, phrases in rules.items() if any(phrase in text for phrase in phrases)]
