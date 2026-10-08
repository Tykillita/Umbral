def words(text: str) -> int:
    return len([w for w in text.split() if w])
