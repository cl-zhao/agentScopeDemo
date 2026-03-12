"""Inspect the raw OpenAI-compatible streaming response directly.

This script bypasses AgentScope and the app SSE adaptation layer. It sends a
single chat completion request with `stream=True` and prints every chunk
exactly as returned by the OpenAI-compatible SDK.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from openai import AsyncClient


def _read_setting(name: str, fallback_name: str | None = None) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    if fallback_name:
        return os.getenv(fallback_name)
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print raw streaming chunks from an OpenAI-compatible model.",
    )
    parser.add_argument(
        "--message",
        default="请直接回答 1+1 等于几，不要调用工具。",
        help="User message to send to the model.",
    )
    parser.add_argument(
        "--api-key",
        default=_read_setting("MODEL_API_KEY", "ARK_API_KEY"),
        help="API key. Defaults to MODEL_API_KEY, then ARK_API_KEY.",
    )
    parser.add_argument(
        "--base-url",
        default=_read_setting("MODEL_BASE_URL", "ARK_BASE_URL"),
        help="Base URL. Defaults to MODEL_BASE_URL, then ARK_BASE_URL.",
    )
    parser.add_argument(
        "--model",
        default=_read_setting("MODEL_NAME", "ARK_MODEL"),
        help="Model name. Defaults to MODEL_NAME, then ARK_MODEL.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="Sampling temperature passed to the model.",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    if not args.api_key or not args.base_url or not args.model:
        print(
            "Missing required settings. Provide --api-key/--base-url/--model "
            "or set MODEL_API_KEY, MODEL_BASE_URL, MODEL_NAME.",
            file=sys.stderr,
        )
        return 1

    client = AsyncClient(
        api_key=args.api_key,
        base_url=args.base_url,
    )

    try:
        stream = await client.chat.completions.create(
            model=args.model,
            messages=[{"role": "user", "content": args.message}],
            stream=True,
            temperature=args.temperature,
        )
        index = 0
        async for chunk in stream:
            payload: dict[str, Any]
            if hasattr(chunk, "model_dump"):
                payload = chunk.model_dump(mode="json")
            else:
                payload = {"raw": str(chunk)}

            print(f"--- chunk {index} ---")
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            index += 1
    finally:
        await client.close()

    return 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
