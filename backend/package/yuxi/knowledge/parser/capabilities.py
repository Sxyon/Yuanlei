"""文档格式与 OCR 处理器能力声明。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

TEXT_FILE_EXTENSIONS = (".txt", ".md")
OFFICE_FILE_EXTENSIONS = (".docx", ".pptx", ".xls", ".xlsx")
HTML_FILE_EXTENSIONS = (".html", ".htm")
IMAGE_FILE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp")
PDF_FILE_EXTENSIONS = (".pdf",)
OCR_FILE_EXTENSIONS = frozenset((*PDF_FILE_EXTENSIONS, *IMAGE_FILE_EXTENSIONS))

SUPPORTED_FILE_EXTENSIONS = (
    *TEXT_FILE_EXTENSIONS,
    *OFFICE_FILE_EXTENSIONS,
    *HTML_FILE_EXTENSIONS,
    ".json",
    ".csv",
    *PDF_FILE_EXTENSIONS,
    *IMAGE_FILE_EXTENSIONS,
    ".zip",
)

_STANDARD_OCR_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif")
_MINERU_OFFICIAL_EXTENSIONS = (".pdf", ".docx", ".pptx", ".png", ".jpg", ".jpeg")
_DEEPSEEK_OCR_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".webp")


@dataclass(frozen=True, slots=True)
class ParserCapability:
    """描述一个 OCR 处理器的装配位置和输入格式。"""

    service_name: str
    display_name: str
    supported_extensions: tuple[str, ...]
    module_path: str
    class_name: str


PARSER_CAPABILITIES = {
    "rapid_ocr": ParserCapability(
        service_name="rapid_ocr",
        display_name="RapidOCR (ONNX)",
        supported_extensions=_STANDARD_OCR_EXTENSIONS,
        module_path="yuxi.knowledge.parser.rapid_ocr",
        class_name="RapidOCRParser",
    ),
    "mineru_ocr": ParserCapability(
        service_name="mineru_ocr",
        display_name="MinerU OCR",
        supported_extensions=_STANDARD_OCR_EXTENSIONS,
        module_path="yuxi.knowledge.parser.mineru",
        class_name="MinerUParser",
    ),
    "mineru_official": ParserCapability(
        service_name="mineru_official",
        display_name="MinerU Official API",
        supported_extensions=_MINERU_OFFICIAL_EXTENSIONS,
        module_path="yuxi.knowledge.parser.mineru_official",
        class_name="MinerUOfficialParser",
    ),
    "pp_structure_v3_ocr": ParserCapability(
        service_name="pp_structure_v3_ocr",
        display_name="PP-Structure-V3",
        supported_extensions=_STANDARD_OCR_EXTENSIONS,
        module_path="yuxi.knowledge.parser.pp_structure_v3",
        class_name="PPStructureV3Parser",
    ),
    "deepseek_ocr": ParserCapability(
        service_name="deepseek_ocr",
        display_name="DeepSeek OCR",
        supported_extensions=_DEEPSEEK_OCR_EXTENSIONS,
        module_path="yuxi.knowledge.parser.deepseek_ocr",
        class_name="DeepSeekOCRParser",
    ),
    "paddleocr_vl_1_6": ParserCapability(
        service_name="paddleocr_vl_1_6",
        display_name="PaddleOCR-VL-1.6",
        supported_extensions=_STANDARD_OCR_EXTENSIONS,
        module_path="yuxi.knowledge.parser.paddleocr_api",
        class_name="PaddleOCRVLParser",
    ),
    "paddleocr_pp_ocrv6": ParserCapability(
        service_name="paddleocr_pp_ocrv6",
        display_name="PP-OCRv6",
        supported_extensions=_STANDARD_OCR_EXTENSIONS,
        module_path="yuxi.knowledge.parser.paddleocr_api",
        class_name="PaddleOCRPPOCRv6Parser",
    ),
}


def get_parser_capability(engine_id: str) -> ParserCapability:
    """返回指定 OCR 处理器的轻量能力声明。"""
    try:
        return PARSER_CAPABILITIES[engine_id]
    except KeyError as exc:
        raise ValueError(f"不支持的 OCR 引擎: {engine_id}") from exc


def get_ocr_engine_ids() -> tuple[str, ...]:
    """返回按注册顺序排列的 OCR 处理器标识。"""
    return tuple(PARSER_CAPABILITIES)


def get_ocr_engines_for_extension(extension: str) -> tuple[str, ...]:
    """返回能处理指定扩展名的 OCR 处理器。"""
    normalized = extension.lower()
    if not normalized.startswith("."):
        normalized = f".{normalized}"
    return tuple(
        engine_id
        for engine_id, capability in PARSER_CAPABILITIES.items()
        if normalized in capability.supported_extensions
    )


def is_supported_file_extension(file_name: str | os.PathLike[str]) -> bool:
    """判断文件名是否属于统一解析器支持的输入格式。"""
    return Path(file_name).suffix.lower() in SUPPORTED_FILE_EXTENSIONS
