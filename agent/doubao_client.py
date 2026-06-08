"""豆包 Pro API 客户端 — chat completions + vision"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional, Union, Any, Dict, List

import requests

from .config import config


class DoubaoClient:
    """豆包 Pro (ARK) API 客户端。

    支持：
    - 文本对话 (/chat/completions)
    - 视觉理解（传入 base64 图片）
    - JSON 结构化输出（通过 response_format）
    """

    def __init__(self):
        self.api_key = config.api_key
        self.base_url = config.base_url
        self.model = config.model
        self.chat_url = f"{self.base_url}/chat/completions"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def chat(
        self,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict] = None,
        retries: int = 3,
        timeout: int = 300,
    ) -> dict:
        """发送 chat completion 请求。

        Args:
            messages: OpenAI 格式的消息列表
            temperature: 采样温度
            max_tokens: 最大输出 token
            response_format: {"type": "json_object"} 启用 JSON 模式
            retries: 重试次数
            timeout: 请求超时秒数（默认300秒用于长生成）

        Returns:
            API 响应 JSON
        """
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else config.temperature,
            "max_tokens": max_tokens or config.max_tokens,
        }
        if response_format:
            body["response_format"] = response_format

        last_error = None
        for attempt in range(retries):
            try:
                resp = requests.post(
                    self.chat_url,
                    headers=self._headers(),
                    json=body,
                    timeout=timeout,
                )
                if resp.status_code == 200:
                    return resp.json()
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:500]}"
                    if resp.status_code == 429:
                        time.sleep(2 ** attempt)
                        continue
                    break
            except requests.RequestException as e:
                last_error = str(e)
                time.sleep(1)
        raise RuntimeError(f"豆包 API 调用失败: {last_error}")

    def get_text(self, resp: dict) -> str:
        """从 API 响应中提取文本内容。"""
        try:
            return resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            return ""

    def chat_text(
        self,
        system_prompt: str,
        user_message: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: int = 300,
    ) -> str:
        """简单文本对话 — 发送 system + user，返回文本。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        resp = self.chat(messages, temperature=temperature, max_tokens=max_tokens, timeout=timeout)
        return self.get_text(resp)

    def chat_json(
        self,
        system_prompt: str,
        user_message: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: int = 300,
    ) -> dict | list:
        """JSON 模式对话 — 要求模型返回 JSON。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        resp = self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            timeout=timeout,
        )
        text = self.get_text(resp)
        return json.loads(text)

    def chat_vision(
        self,
        system_prompt: str,
        user_text: str,
        image_paths: list[Path],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: int = 300,
    ) -> str:
        """视觉对话 — 发送文本 + 图片列表，返回文本分析结果。

        Args:
            system_prompt: 系统提示
            user_text: 用户文本指令
            image_paths: 本地图片路径列表
            temperature: 采样温度
            max_tokens: 最大输出 token

        Returns:
            模型返回的文本
        """
        from .utils import image_to_base64

        content = [{"type": "text", "text": user_text}]
        for p in image_paths:
            content.append({
                "type": "image_url",
                "image_url": {"url": image_to_base64(p)},
            })

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ]

        # vision 模式需要更多 token
        vision_max_tokens = max_tokens or 8192
        resp = self.chat(
            messages,
            temperature=temperature or 0.3,
            max_tokens=vision_max_tokens,
            timeout=timeout,
        )
        return self.get_text(resp)

    def chat_vision_json(
        self,
        system_prompt: str,
        user_text: str,
        image_paths: list[Path],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: int = 300,
    ) -> dict | list:
        """视觉 + JSON 模式 — 发送文本 + 图片，要求返回结构化 JSON。"""
        from .utils import image_to_base64

        content = [{"type": "text", "text": user_text}]
        for p in image_paths:
            content.append({
                "type": "image_url",
                "image_url": {"url": image_to_base64(p)},
            })

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ]

        vision_max_tokens = max_tokens or 8192
        resp = self.chat(
            messages,
            temperature=temperature or 0.3,
            max_tokens=vision_max_tokens,
            response_format={"type": "json_object"},
            timeout=timeout,
        )
        text = self.get_text(resp)
        return json.loads(text)


# 全局客户端实例
client = DoubaoClient()
