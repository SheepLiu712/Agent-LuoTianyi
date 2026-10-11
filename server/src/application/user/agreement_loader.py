import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast


class AgreementConfigError(Exception):
    """协议配置非法，启动时必须拒绝。"""


@dataclass(frozen=True)
class AgreementFormat:
    align_values: frozenset[str]
    min_font_size: int
    max_font_size: int
    default_font_size: int
    default_align: str
    block_keys: frozenset[str]
    run_keys: frozenset[str]


@dataclass(frozen=True)
class AgreementDoc:
    version: str
    title: str
    format: str
    blocks: list[dict[str, object]]
    content_json: str
    sha256: str


ALLOWED_MANIFEST_KEYS: frozenset[str] = frozenset({"current_version", "files"})
ALLOWED_TOP_KEYS: frozenset[str] = frozenset({"version", "title", "format", "blocks"})


AGREEMENT_FORMATS: dict[str, AgreementFormat] = {
    "agreement.richtext.v1": AgreementFormat(
        align_values=frozenset({"center", "justify"}),
        min_font_size=12,
        max_font_size=32,
        default_font_size=16,
        default_align="justify",
        block_keys=frozenset({"font_size", "align", "runs"}),
        run_keys=frozenset({"text", "bold"}),
    ),
}


def load_manifest(root: Path) -> tuple[str, dict[str, AgreementDoc]]:
    manifest = _read_json(root / "manifest.json")
    current_version = _validate_manifest(manifest)

    docs: dict[str, AgreementDoc] = {}
    for version, filename in manifest["files"].items():
        docs[version] = _load_doc(root / filename, version)

    if current_version not in docs:
        raise AgreementConfigError(f"current_version {current_version} 不在 files 中")

    return current_version, docs


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise AgreementConfigError(f"协议文件不存在: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AgreementConfigError(f"协议文件不是合法 JSON: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise AgreementConfigError(f"协议文件顶层必须是对象: {path}")
    return raw


def _validate_manifest(manifest: dict) -> str:
    unknown = set(manifest.keys()) - ALLOWED_MANIFEST_KEYS
    if unknown:
        raise AgreementConfigError(f"manifest 含未知字段: {sorted(unknown)}")

    current = manifest.get("current_version")
    if not isinstance(current, str) or not current:
        raise AgreementConfigError("manifest.current_version 必须是非空字符串")

    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise AgreementConfigError("manifest.files 必须是非空对象")

    for version, filename in files.items():
        if not isinstance(version, str) or not version:
            raise AgreementConfigError("manifest.files 的 key 必须是非空字符串")
        if not isinstance(filename, str) or not filename:
            raise AgreementConfigError(f"manifest.files[{version}] 必须是非空字符串")

    return current


def _load_doc(path: Path, expected_version: str) -> AgreementDoc:
    raw = _read_json(path)

    unknown = set(raw.keys()) - ALLOWED_TOP_KEYS
    if unknown:
        raise AgreementConfigError(f"{path} 含未知字段: {sorted(unknown)}")

    version, title, fmt = _validate_doc_header(raw, expected_version, path)
    spec = AGREEMENT_FORMATS[fmt]
    blocks = _validate_blocks(raw, path, spec)

    canonical = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    return AgreementDoc(
        version=version,
        title=title,
        format=fmt,
        blocks=blocks,
        content_json=canonical,
        sha256=sha,
    )


def _validate_doc_header(raw: dict, expected_version: str, path: Path) -> tuple[str, str, str]:
    version = raw.get("version")
    if not isinstance(version, str) or not version:
        raise AgreementConfigError(f"{path} version 必须是非空字符串")
    if version != expected_version:
        raise AgreementConfigError(f"{path} version {version} 与 manifest key {expected_version} 不一致")

    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise AgreementConfigError(f"{path} title 必须是非空字符串")

    fmt = raw.get("format")
    if not isinstance(fmt, str) or fmt not in AGREEMENT_FORMATS:
        raise AgreementConfigError(f"{path} 不支持的 format: {fmt!r}，支持: {sorted(AGREEMENT_FORMATS)}")

    return version, title, fmt


def _validate_blocks(raw: dict, path: Path, spec: AgreementFormat) -> list[dict[str, object]]:
    blocks = raw.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise AgreementConfigError(f"{path} blocks 必须是非空数组")

    has_text = False
    for index, block in enumerate(blocks):
        if _validate_block(block, index, path, spec):
            has_text = True

    if not has_text:
        raise AgreementConfigError(f"{path} 正文至少需要一个非空白字符")

    return cast(list[dict[str, object]], blocks)


def _validate_block(block, index: int, path: Path, spec: AgreementFormat) -> bool:
    if not isinstance(block, dict):
        raise AgreementConfigError(f"{path} blocks[{index}] 必须是对象")

    unknown = set(block.keys()) - spec.block_keys
    if unknown:
        raise AgreementConfigError(f"{path} blocks[{index}] 含未知字段: {sorted(unknown)}")

    size = block.get("font_size", spec.default_font_size)
    if isinstance(size, bool) or not isinstance(size, int):
        raise AgreementConfigError(f"{path} blocks[{index}].font_size 必须是整数")
    if not (spec.min_font_size <= size <= spec.max_font_size):
        raise AgreementConfigError(
            f"{path} blocks[{index}].font_size 必须在 " f"{spec.min_font_size}-{spec.max_font_size}"
        )

    align = block.get("align", spec.default_align)
    if align not in spec.align_values:
        raise AgreementConfigError(
            f"{path} blocks[{index}].align 非法: {align!r}，" f"只允许 {sorted(spec.align_values)}"
        )

    runs = block.get("runs")
    if not isinstance(runs, list) or not runs:
        raise AgreementConfigError(f"{path} blocks[{index}].runs 必须是非空数组")

    has_text = False
    for run_index, run in enumerate(runs):
        if _validate_run(run, index, run_index, path, spec):
            has_text = True

    return has_text


def _validate_run(run, block_index: int, run_index: int, path: Path, spec: AgreementFormat) -> bool:
    if not isinstance(run, dict):
        raise AgreementConfigError(f"{path} blocks[{block_index}].runs[{run_index}] 必须是对象")

    unknown = set(run.keys()) - spec.run_keys
    if unknown:
        raise AgreementConfigError(f"{path} blocks[{block_index}].runs[{run_index}] 含未知字段: {sorted(unknown)}")

    text = run.get("text")
    if not isinstance(text, str):
        raise AgreementConfigError(f"{path} blocks[{block_index}].runs[{run_index}].text 必须是字符串")

    bold = run.get("bold", False)
    if not isinstance(bold, bool):
        raise AgreementConfigError(f"{path} blocks[{block_index}].runs[{run_index}].bold 必须是布尔值")

    return bool(text.strip())
