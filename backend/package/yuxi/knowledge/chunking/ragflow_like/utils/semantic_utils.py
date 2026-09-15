from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from sklearn.cluster import AgglomerativeClustering

_ENGLISH_ABBREVIATIONS = {
    "approx.",
    "dept.",
    "dr.",
    "e.g.",
    "etc.",
    "i.e.",
    "jr.",
    "mr.",
    "mrs.",
    "ms.",
    "no.",
    "prof.",
    "rev.",
    "sr.",
    "st.",
    "vs.",
}
_ENGLISH_TITLE_ABBREVIATIONS = {"dr.", "jr.", "mr.", "mrs.", "ms.", "prof.", "rev.", "sr.", "st."}
_ENGLISH_SENTENCE_STARTERS = {
    "he",
    "however",
    "i",
    "it",
    "meanwhile",
    "next",
    "she",
    "that",
    "then",
    "these",
    "this",
    "those",
    "they",
    "we",
    "you",
}


def semantic_chunking_with_auto_clusters(
    text: str,
    embed_fn: Callable[[list[str]], Any] | None,
    token_count_fn: Callable[[str], int],
    max_chunk_size: int = 512,
) -> list[str]:
    """
    对传入的文本进行语义切分，过程中会自动选择最佳的聚集数量。

    逻辑：
    - 先将文本中的句子按语言进行分发，英文/混合文本使用标准库分句，中文文本使用split_sentences_chinese。
    - 对每个句子进行嵌入向量化。
    - 确定最佳的聚类数量（根据轮廓系数）。
    - 对句子进行聚类后，按原文顺序遍历：当聚类标签变化或达到长度上限时切分，形成连续分块。
    - 如果嵌入模型缺失，则退化为原始切分方式
    """
    sentences = split_mixed_sentences(text)
    if len(sentences) < 2:
        return [text.strip()]

    # 计算每个句子的token数量
    sentence_token_counts = [token_count_fn(s) for s in sentences]
    total_tokens = sum(sentence_token_counts)

    # 如果没有提供向量化函数，或者整体未超长，则直接进行简单合并/返回
    if embed_fn is None or total_tokens <= max_chunk_size:
        chunks = []
        current_chunk = ""
        current_chunk_tokens = 0
        for s, cnt in zip(sentences, sentence_token_counts):
            if current_chunk_tokens + cnt > max_chunk_size and current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = s
                current_chunk_tokens = cnt
            else:
                current_chunk += s
                current_chunk_tokens += cnt
        if current_chunk:
            chunks.append(current_chunk.strip())
        return chunks

    # 向量化每个句子, 得到他们的嵌入向量
    embeddings = embed_fn(sentences)

    # 决定合适的聚集数量：超长时按上限向上取整，避免整除时多切一块
    best_k = (total_tokens + max_chunk_size - 1) // max_chunk_size
    best_k = min(best_k, len(sentences))

    # 根据指定的聚集数量、相似度判断方式、联动方式，对句子进行聚类
    # labels 是每个句子的聚类标签列表（如 [0,0,1,2,2]），后续会按原文顺序在标签变化处切分连续分块
    labels = AgglomerativeClustering(n_clusters=best_k, metric="cosine", linkage="average").fit_predict(embeddings)

    chunks = []
    current_chunk = ""
    current_chunk_tokens = 0
    current_label = labels[0]

    for sentence, label, token_count in zip(sentences, labels, sentence_token_counts):
        if label != current_label or current_chunk_tokens + token_count > max_chunk_size:
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            current_chunk = sentence
            current_chunk_tokens = token_count
            current_label = label
        else:
            current_chunk += sentence
            current_chunk_tokens += token_count

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def split_mixed_sentences(text: str) -> list[str]:
    """
    处理中英文混合文本的分句逻辑，支持按物理段落分发不同的分句策略。

    该函数采用“分而治之”的策略来处理复杂的混合文本：
    1. **物理分块**：首先按换行符 (`\\n+`) 将原始文本切分为多个物理段落（chunks），确保物理结构不被破坏。
    2. **语言检测与分发**：
       - **英文/混合路径**：若段落中包含英文字母 (`[A-Za-z]`)，则视为英文或混合文本，
         使用标准库按句末标点分句，并保留常见英文缩写、数字和引号边界。
       - **中文路径**：若段落不含字母，则视为纯中文文本，调用 `split_sentences_chinese`。
         该方法通过正则精准匹配中文标点及后续引号。
       - **兜底方案**：若上述方法未产生结果，则使用简单的正则表达式按中文标点强制分割。
    3. **清洗与过滤**：汇总所有子句，去除两端空白字符，并过滤掉空字符串。

    Args:
        text: 待分句的原始字符串。

    Returns:
        List[str]: 分割后的句子列表。
    """
    chunks = re.split(r"(\n+)", text)
    sentences = []

    for ch in chunks:
        if not ch.strip():
            continue
        if re.search(r"[A-Za-z]", ch):
            parts = _split_english_sentences(ch)
            sentences.extend([p.strip() for p in parts if p.strip()])
        else:
            sents = split_sentences_chinese(ch)
            if sents:
                sentences.extend([s.strip() for s in sents if s.strip()])
            else:
                parts = re.split(r"(?<=[。！？])", ch)
                sentences.extend([p.strip() for p in parts if p.strip()])
    return sentences


def split_sentences_chinese(text: str) -> list[str]:
    """
    使用正则表达式将中文文本分割成句子。

    逻辑：
    - 匹配中文句号、感叹号、问号（。！？）作为分隔点。
    - 使用正向/反向预查处理引号：确保如果标点后面紧跟引号（”’"），该引号会被保留在当前句子末尾，而不是被切分到下一句。
    - 返回去除两端空格且非空的句子列表。
    """
    pattern = r'(?<=[。！？][”’"])|(?<=[。！？])(?![”’"])'
    sentences = re.split(pattern, text)
    return [s.strip() for s in sentences if s.strip()]


def _split_english_sentences(text: str) -> list[str]:
    """使用标准库按英文句末标点分句，并保留常见缩写。"""
    sentences: list[str] = []
    start = 0
    index = 0
    closing_chars = "\"'”’)]}"

    while index < len(text):
        if text[index] not in ".!?。！？":
            index += 1
            continue

        punctuation_end = index + 1
        while punctuation_end < len(text) and text[punctuation_end] in ".!?。！？":
            punctuation_end += 1
        boundary_end = punctuation_end
        while boundary_end < len(text) and text[boundary_end] in closing_chars:
            boundary_end += 1

        is_boundary = boundary_end == len(text) or text[boundary_end].isspace()
        if text[index] == "." and _is_english_abbreviation(text, start, index):
            is_boundary = False
        if is_boundary:
            sentence = text[start:boundary_end].strip()
            if sentence:
                sentences.append(sentence)
            start = boundary_end
        index = boundary_end

    remainder = text[start:].strip()
    if remainder:
        sentences.append(remainder)
    return sentences


def _is_english_abbreviation(text: str, start: int, punctuation: int) -> bool:
    """判断句点是否属于常见英文缩写或单字母首字母。"""
    prefix = text[start : punctuation + 1].rstrip()
    match = re.search(r"([A-Za-z](?:[A-Za-z.]*)\.)$", prefix)
    if match is None:
        return False

    token = match.group(1).lower()
    letters = token.replace(".", "")
    if token in _ENGLISH_TITLE_ABBREVIATIONS:
        return True
    next_index = punctuation + 1
    while next_index < len(text) and text[next_index].isspace():
        next_index += 1
    next_character = text[next_index] if next_index < len(text) else ""
    if token in _ENGLISH_ABBREVIATIONS:
        return bool(next_character) and next_character.islower()
    if len(letters) == 1:
        return True
    if re.fullmatch(r"(?:[A-Z]\.){2,}", match.group(1)):
        next_word = re.match(r"[A-Za-z]+", text[next_index:])
        return next_word is not None and next_word.group(0).lower() not in _ENGLISH_SENTENCE_STARTERS
    if re.fullmatch(r"(?:[a-z]\.){2,}", token):
        return next_index == len(text) or text[next_index].islower()
    return False
