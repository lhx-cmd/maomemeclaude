"""Seedream 图像生成客户端 — 通过 ARK API 调用 Seedream 模型"""

from __future__ import annotations

import time
import base64
from pathlib import Path

import requests

from .config import config
from .utils import save_json
from .generated_asset_library import find_reusable_asset, write_asset_meta


class SeedreamClient:
    """Seedream 图像生成客户端。

    通过 ARK API 的图像生成接口调用 Seedream 模型，
    用于生成贴纸、道具、背景图等补充素材。
    """

    def __init__(self):
        self.api_key = config.api_key
        self.base_url = config.base_url
        self.model = config.seedream_model
        self.images_url = f"{self.base_url}/images/generations"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def generate(
        self,
        prompt: str,
        size: str = "1024x1024",
        n: int = 1,
        style: str = "illustration",
        negative_prompt: str = "",
        retries: int = 3,
    ) -> list[dict]:
        """生成图像。

        Args:
            prompt: 图像生成提示词
            size: 图像尺寸，如 "1024x1024", "512x512", "1792x1024"
            n: 生成数量
            style: 风格描述
            negative_prompt: 负向提示词
            retries: 重试次数

        Returns:
            [{"b64_json": "...", "revised_prompt": "..."}, ...]
        """
        full_prompt = f"{prompt}, {style}, high quality, clean design, sticker style"

        body = {
            "model": self.model,
            "prompt": full_prompt,
            "size": size,
            "n": n,
            "response_format": "b64_json",
        }
        if negative_prompt:
            body["negative_prompt"] = negative_prompt

        last_error = None
        for attempt in range(retries):
            try:
                resp = requests.post(
                    self.images_url,
                    headers=self._headers(),
                    json=body,
                    timeout=180,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("data", [])
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:500]}"
                    if resp.status_code == 429:
                        time.sleep(2 ** attempt)
                        continue
                    break
            except requests.RequestException as e:
                last_error = str(e)
                time.sleep(1)

        raise RuntimeError(f"Seedream 图像生成失败: {last_error}")

    def generate_and_save(
        self,
        prompt: str,
        output_path: Path,
        size: str = "1024x1024",
        style: str = "illustration, sticker style, cute cartoon",
        negative_prompt: str = "",
        asset_kind: str = "",
        description: str = "",
    ) -> Path:
        """生成图像并保存到本地。

        Args:
            prompt: 图像生成提示词
            output_path: 输出文件路径（.png）
            size: 图像尺寸
            style: 风格
            negative_prompt: 负向提示词

        Returns:
            保存的文件路径
        """
        results = self.generate(
            prompt=prompt,
            size=size,
            n=1,
            style=style,
            negative_prompt=negative_prompt,
        )

        if not results:
            raise RuntimeError("Seedream 未返回图像数据")

        image_data = results[0].get("b64_json", "")
        if not image_data:
            raise RuntimeError("Seedream 返回数据中缺少 b64_json")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(image_data))

        generated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        revised_prompt = results[0].get("revised_prompt", prompt)
        if asset_kind:
            write_asset_meta(
                output_path=output_path,
                asset_kind=asset_kind,
                description=description,
                prompt=prompt,
                size=size,
                style=style,
                revised_prompt=revised_prompt,
                generated_at=generated_at,
            )
        else:
            # 保存生成元数据
            meta_path = output_path.with_suffix(".meta.json")
            save_json(meta_path, {
                "prompt": prompt,
                "size": size,
                "style": style,
                "revised_prompt": revised_prompt,
                "generated_at": generated_at,
            })

        return output_path

    def generate_sticker(
        self,
        description: str,
        name: str,
        category: str = "generated",
    ) -> Path:
        """生成贴纸/小道具。

        Args:
            description: 贴纸描述
            name: 贴纸名称（用于文件名）
            category: 分类名

        Returns:
            保存的文件路径
        """
        output_path = config.generated_dir / "stickers" / category / f"{name}.png"
        reusable = find_reusable_asset("sticker", description, expected_size="1920x1920")
        if reusable:
            return reusable
        return self.generate_and_save(
            prompt=f"A cute cartoon sticker of {description}, "
                    f"transparent background style, simple clean design, "
                    f"suitable for meme video overlay, white stroke outline",
            output_path=output_path,
            size="1920x1920",
            style="sticker, cartoon, cute, simple, transparent background ready",
            negative_prompt="photo, realistic, complex background, text, watermark",
            asset_kind="sticker",
            description=description,
        )

    def generate_background(
        self,
        description: str,
        name: str,
    ) -> Path:
        """生成背景图。

        Args:
            description: 场景描述
            name: 背景名称（用于文件名）

        Returns:
            保存的文件路径
        """
        output_path = config.generated_dir / "backgrounds" / f"{name}.png"
        reusable = find_reusable_asset("background", description, expected_size="2560x1440")
        if reusable:
            return reusable
        return self.generate_and_save(
            prompt=f"A simple 16:9 landscape cartoon background scene of {description}, "
                    f"soft colors, minimal detail, suitable as video background, "
                    f"flat illustration style, no characters in the scene",
            output_path=output_path,
            size="2560x1440",
            style="16:9 landscape, flat illustration, cartoon background, soft colors, minimal, no characters",
            negative_prompt="characters, people, animals, text, watermark, complex, photorealistic",
            asset_kind="background",
            description=description,
        )

    def generate_prop(
        self,
        description: str,
        name: str,
    ) -> Path:
        """生成道具/物件图。

        Args:
            description: 道具描述
            name: 道具名称（用于文件名）

        Returns:
            保存的文件路径
        """
        output_path = config.generated_dir / "props" / f"{name}.png"
        reusable = find_reusable_asset("prop", description, expected_size="1920x1920")
        if reusable:
            return reusable
        return self.generate_and_save(
            prompt=f"A cute cartoon prop of {description}, "
                    f"isolated object, clean edges, suitable for cat meme video, "
                    f"simple design, vibrant colors, sticker style",
            output_path=output_path,
            size="1920x1920",
            style="cute cartoon prop, isolated object, sticker style, vibrant, clean edges",
            negative_prompt="background, scene, text, watermark, realistic, complex",
            asset_kind="prop",
            description=description,
        )


# 全局客户端实例
seedream = SeedreamClient()
