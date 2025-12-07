def compress_message(content: str, max_len: int = 200) -> str:
    # Simple heuristic: truncate; later you can use Gemini to summarize
    content = content.strip().replace("\n", " ")
    if len(content) <= max_len:
        return content
    return content[: max_len - 3] + "..."
