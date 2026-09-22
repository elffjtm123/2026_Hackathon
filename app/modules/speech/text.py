def merge_transcript(existing: str, incoming: str) -> tuple[str, str]:
    current = existing.strip()
    next_text = incoming.strip()
    if not next_text or next_text in current:
        return current, ""
    if not current:
        return next_text, next_text

    left = current.split()
    right = next_text.split()
    overlap = 0
    for size in range(min(len(left), len(right)), 0, -1):
        if left[-size:] == right[:size]:
            overlap = size
            break
    novel = " ".join(right[overlap:])
    return " ".join([current, novel]).strip(), novel
