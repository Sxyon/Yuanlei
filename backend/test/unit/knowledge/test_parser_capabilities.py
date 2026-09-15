from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from yuxi.knowledge.parser.capabilities import (
    IMAGE_FILE_EXTENSIONS,
    PARSER_CAPABILITIES,
    SUPPORTED_FILE_EXTENSIONS,
    get_ocr_engines_for_extension,
    is_supported_file_extension,
)

pytestmark = pytest.mark.unit


def test_capability_metadata_covers_upload_and_ocr_formats() -> None:
    assert ".webp" in IMAGE_FILE_EXTENSIONS
    assert ".webp" in SUPPORTED_FILE_EXTENSIONS
    assert ".doc" not in SUPPORTED_FILE_EXTENSIONS
    assert ".ppt" not in SUPPORTED_FILE_EXTENSIONS
    assert get_ocr_engines_for_extension("webp") == ("deepseek_ocr",)
    assert get_ocr_engines_for_extension("docx") == ("mineru_official",)
    assert get_ocr_engines_for_extension("ppt") == ()
    assert is_supported_file_extension("report.PPTX")
    assert not is_supported_file_extension("legacy.doc")


def test_capability_lookup_does_not_load_concrete_parser_modules() -> None:
    package_dir = Path(__file__).resolve().parents[3] / "package"
    script = f"""
import sys
sys.path.insert(0, {str(package_dir)!r})
from yuxi.knowledge.parser.capabilities import get_parser_capability

get_parser_capability("rapid_ocr")
assert "yuxi.knowledge.parser.rapid_ocr" not in sys.modules
assert "docling" not in sys.modules
"""

    subprocess.run([sys.executable, "-c", script], check=True)


def test_knowledge_router_import_does_not_load_docling_or_ocr_provider() -> None:
    backend_dir = Path(__file__).resolve().parents[3]
    package_dir = backend_dir / "package"
    script = f"""
import sys
sys.path.insert(0, {str(package_dir)!r})
sys.path.insert(0, {str(backend_dir)!r})
import server.routers.knowledge_router

assert "docling" not in sys.modules
assert "yuxi.knowledge.parser.rapid_ocr" not in sys.modules
assert "yuxi.knowledge.parser.mineru" not in sys.modules
"""

    subprocess.run([sys.executable, "-c", script], check=True)


@pytest.mark.asyncio
async def test_parse_document_rejects_ocr_engine_without_format_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yuxi.services import ocr_service

    source = tmp_path / "scan.webp"
    source.write_bytes(b"not an image")

    async def _resolve_rapid_ocr(*args, **kwargs) -> dict[str, str]:
        del args, kwargs
        return {"ocr_engine": "rapid_ocr"}

    monkeypatch.setattr(ocr_service, "resolve_ocr_task_params", _resolve_rapid_ocr)

    with pytest.raises(ValueError, match=r"不支持文件类型 \.webp"):
        await ocr_service.parse_document(str(source), params={"ocr_engine": "rapid_ocr"})


def test_capability_registry_declares_shipping_processors() -> None:
    assert tuple(PARSER_CAPABILITIES) == (
        "rapid_ocr",
        "mineru_ocr",
        "mineru_official",
        "pp_structure_v3_ocr",
        "deepseek_ocr",
        "paddleocr_vl_1_6",
        "paddleocr_pp_ocrv6",
    )


@pytest.mark.asyncio
async def test_zip_parser_returns_markdown_text_without_sidecar_metadata(tmp_path: Path) -> None:
    from yuxi.knowledge.parser.zip_utils import process_zip_file

    archive = tmp_path / "result.zip"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("full.md", "# Parsed ZIP document")

    result = await process_zip_file(str(archive))

    assert result == "# Parsed ZIP document"
    assert isinstance(result, str)
