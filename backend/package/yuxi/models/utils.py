"""从模型标准块投影展示正文；旧持久消息只在这里尽力恢复。"""

import re


def parse_assistant_message_body(content: str | list, metadata: dict | None = None) -> dict[str, str]:
    """投影标准块；显式传入历史 metadata 时才尝试恢复旧格式。"""
    history = metadata if isinstance(metadata, dict) else {}
    blocks = content if isinstance(content, list) else history.get("content", [])
    text_parts = []
    reasoning_parts = []
    if isinstance(blocks, list):
        for block in blocks:
            match block:
                case {"type": "text", "text": str(value)}:
                    text_parts.append(value)
                case {"type": "reasoning", "reasoning": str(value)}:
                    reasoning_parts.append(value)

    text = content if isinstance(content, str) else "".join(text_parts)
    reasoning = "".join(reasoning_parts)
    if metadata is None:
        return {"content": text, "reasoning_content": reasoning}
    if not reasoning:
        for source in (history, history.get("additional_kwargs")):
            if not isinstance(source, dict):
                continue
            value = source.get("reasoning_content")
            if isinstance(value, str) and value:
                reasoning = value
                break
    if not reasoning and (match := re.match(r"^\s*<think>(.*?)(?:</think>|$)", text, re.DOTALL)):
        reasoning = match.group(1)
        text = text[match.end() :]
    return {"content": text, "reasoning_content": reasoning}
