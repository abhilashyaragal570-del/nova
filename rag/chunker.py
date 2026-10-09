"""Split text into overlapping chunks for document search.

Pure function: no files, no network. A chunk ends at the best natural break
in the second half of its window (blank line, new line, sentence end, space),
so chunks rarely cut a sentence in two. The next chunk starts a little
earlier, so a fact near a boundary appears whole in at least one chunk.
"""

DEFAULT_MAX_CHARS = 1200
DEFAULT_OVERLAP = 200
_BREAKS = ("\n\n", "\n", ". ", " ")


def _cut_point(text: str, start: int, end: int, max_chars: int) -> int:
    floor = start + max_chars // 2
    for sep in _BREAKS:
        i = text.rfind(sep, floor, end)
        if i != -1:
            return i + len(sep)
    return end  # no break found: cut hard at the limit


def chunk_text(
    text: str, max_chars: int = DEFAULT_MAX_CHARS, overlap: int = DEFAULT_OVERLAP
) -> list[str]:
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    if max_chars < 1 or overlap < 0 or overlap >= max_chars // 2:
        raise ValueError("overlap must be smaller than half of max_chars")
    text = text.replace("\r\n", "\n").strip()
    chunks: list[str] = []
    start, length = 0, len(text)
    while start < length:
        end = min(start + max_chars, length)
        if end < length:
            end = _cut_point(text, start, end, max_chars)
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return chunks