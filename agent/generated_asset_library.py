"""Generated asset library for reusing Seedream-created media."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import config
from .utils import load_json, save_json


ASSET_FOLDERS = {
    "background": "backgrounds",
    "prop": "props",
    "sticker": "stickers",
}


def find_reusable_asset(
    asset_kind: str,
    description: str,
    expected_size: str = "",
) -> Path | None:
    """Find a previously generated asset with a matching description."""
    query_tokens = _tokens(description)
    if not query_tokens:
        return None

    best_path = None
    best_score = 0.0
    for image_path, meta in iter_generated_assets(asset_kind, prefer_index=True):
        if expected_size and str(meta.get("size", "")) != expected_size:
            continue

        corpus = " ".join(
            str(meta.get(key, ""))
            for key in ("description", "prompt", "revised_prompt", "style")
        )
        score = _similarity(query_tokens, _tokens(corpus))
        if score > best_score:
            best_score = score
            best_path = image_path

    return best_path if best_score >= 0.75 else None


def iter_generated_assets(asset_kind: str, prefer_index: bool = False):
    """Yield `(image_path, meta)` pairs for generated assets of one kind."""
    folder = ASSET_FOLDERS.get(asset_kind)
    if not folder:
        return

    root = config.generated_dir / folder
    if not root.exists():
        return

    if prefer_index:
        indexed_assets = _load_index_assets(asset_kind)
        if indexed_assets:
            for item in indexed_assets:
                image_path = Path(str(item.get("file", "")))
                if image_path.exists():
                    yield image_path, item
            return

    for meta_path in root.rglob("*.meta.json"):
        image_path = _image_path_for_meta(meta_path)
        if not image_path or not image_path.exists():
            continue

        meta = load_asset_meta(meta_path)
        if meta.get("asset_kind") and meta.get("asset_kind") != asset_kind:
            continue
        yield image_path, meta


def rebuild_asset_index(asset_kind: str) -> dict[str, Any]:
    """Create a summary index that agents can browse quickly."""
    folder = ASSET_FOLDERS.get(asset_kind)
    if not folder:
        raise ValueError(f"Unsupported asset kind: {asset_kind}")

    root = config.generated_dir / folder
    root.mkdir(parents=True, exist_ok=True)
    assets = []
    for image_path, meta in iter_generated_assets(asset_kind, prefer_index=False):
        description = str(meta.get("description", "")).strip() or _derive_description_from_prompt(
            str(meta.get("prompt", ""))
        )
        assets.append({
            "file": str(image_path),
            "description": description,
            "prompt": str(meta.get("prompt", "")),
            "revised_prompt": str(meta.get("revised_prompt", "")),
            "size": str(meta.get("size", "")),
            "style": str(meta.get("style", "")),
            "generated_at": str(meta.get("generated_at", "")),
        })
    assets.sort(key=lambda item: (item.get("description", ""), item.get("file", "")))
    index = {
        "asset_kind": asset_kind,
        "folder": str(root),
        "count": len(assets),
        "assets": assets,
    }
    save_json(_index_path(asset_kind), index)
    return index


def asset_index_context(asset_kind: str, limit: int = 30) -> str:
    """Return a compact human-readable index for model prompts."""
    assets = _load_index_assets(asset_kind)
    if not assets:
        try:
            assets = rebuild_asset_index(asset_kind).get("assets", [])
        except Exception:
            assets = []
    if not assets:
        return ""

    title = {
        "background": "## 已生成背景素材库（可复用，优先选择语义相近项）",
        "prop": "## 已生成道具素材库（可复用，优先选择语义相近项）",
        "sticker": "## 已生成贴纸素材库（可复用，优先选择语义相近项）",
    }.get(asset_kind, f"## 已生成{asset_kind}素材库")
    lines = [title]
    for item in assets[:limit]:
        lines.append(
            f"- {item.get('description', '')}: {item.get('file', '')} "
            f"[size: {item.get('size', '')}]"
        )
    return "\n".join(lines)


def write_asset_meta(
    output_path: Path,
    asset_kind: str,
    description: str,
    prompt: str,
    size: str,
    style: str,
    revised_prompt: str,
    generated_at: str,
) -> None:
    """Write reusable metadata next to a generated asset."""
    save_json(output_path.with_suffix(".meta.json"), {
        "asset_kind": asset_kind,
        "description": description,
        "prompt": prompt,
        "size": size,
        "style": style,
        "revised_prompt": revised_prompt,
        "generated_at": generated_at,
    })
    try:
        rebuild_asset_index(asset_kind)
    except Exception:
        pass


def load_asset_meta(meta_path: Path) -> dict[str, Any]:
    try:
        data = load_json(meta_path)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _image_path_for_meta(meta_path: Path) -> Path | None:
    base = meta_path.name.removesuffix(".meta.json")
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        candidate = meta_path.with_name(base + ext)
        if candidate.exists():
            return candidate
    return None


def _index_path(asset_kind: str) -> Path:
    folder = ASSET_FOLDERS[asset_kind]
    return config.generated_dir / folder / "index.json"


def _load_index_assets(asset_kind: str) -> list[dict[str, Any]]:
    try:
        index = load_json(_index_path(asset_kind))
    except Exception:
        return []
    if not isinstance(index, dict):
        return []
    if index.get("asset_kind") != asset_kind:
        return []
    assets = index.get("assets", [])
    return assets if isinstance(assets, list) else []


def _derive_description_from_prompt(prompt: str) -> str:
    match = re.search(r"scene of (.*?), soft colors", prompt)
    if match:
        return match.group(1).strip()
    return ""


def _tokens(text: str) -> set[str]:
    normalized = str(text).lower()
    ascii_tokens = set(re.findall(r"[a-z0-9]+", normalized))
    cjk_tokens = {ch for ch in normalized if "\u4e00" <= ch <= "\u9fff"}
    return ascii_tokens | cjk_tokens


def _similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left)
