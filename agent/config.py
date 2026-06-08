"""配置加载模块 — 从 .env 文件读取 ARK API 配置"""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field


def _load_dotenv(dotenv_path: Path) -> dict[str, str]:
    """简易 .env 解析器，避免额外依赖。"""
    env_vars = {}
    if not dotenv_path.exists():
        return env_vars
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            env_vars[key.strip()] = value.strip()
    return env_vars


# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 加载 .env（不覆盖已有的环境变量）
_dotenv = _load_dotenv(PROJECT_ROOT / ".env")
for k, v in _dotenv.items():
    if k not in os.environ:
        os.environ[k] = v


@dataclass
class Config:
    """ARK / 豆包 API 配置"""

    api_key: str = field(
        default_factory=lambda: os.environ.get("ARK_API_KEY", "")
    )
    base_url: str = field(
        default_factory=lambda: os.environ.get(
            "ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
        )
    )
    model: str = field(
        default_factory=lambda: os.environ.get(
            "ARK_MODEL", "doubao-seed-2-0-pro-260215"
        )
    )
    seedream_model: str = field(
        default_factory=lambda: os.environ.get(
            "SEEDREAM_MODEL", "doubao-seedream-4-0"
        )
    )
    seedream_max_workers: int = field(
        default_factory=lambda: int(os.environ.get("SEEDREAM_MAX_WORKERS", "5"))
    )

    # 路径
    assets_root: Path = PROJECT_ROOT / "assets"
    baokuan_raw: Path = PROJECT_ROOT / "assets" / "baokuan" / "raw"
    baokuan_structure: Path = PROJECT_ROOT / "assets" / "baokuan" / "structure"
    cat_motions_dir: Path = PROJECT_ROOT / "assets" / "cat-motions"
    stickers_dir: Path = PROJECT_ROOT / "assets" / "stickers"
    generated_dir: Path = PROJECT_ROOT / "assets" / "generated"

    # 分析参数
    max_analysis_frames: int = 15
    frame_interval_seconds: float = 2.0
    max_tokens: int = 4096
    temperature: float = 0.7

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


# 全局单例
config = Config()
