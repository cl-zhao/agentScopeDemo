"""safe_python 模块单元测试。"""

from __future__ import annotations

import pytest

from app.tools.safe_python import PythonSafetyConfig, SafePythonExecutor


def _extract_text_content(tool_response_text: str) -> tuple[str, str]:
    """从 XML 风格工具结果中提取 stdout/stderr。

    参数:
        tool_response_text: 工具结果原始文本。

    返回:
        tuple[str, str]: stdout 和 stderr 字符串。
    """
    stdout_start = tool_response_text.find("<stdout>") + len("<stdout>")
    stdout_end = tool_response_text.find("</stdout>")
    stderr_start = tool_response_text.find("<stderr>") + len("<stderr>")
    stderr_end = tool_response_text.find("</stderr>")
    stdout = tool_response_text[stdout_start:stdout_end]
    stderr = tool_response_text[stderr_start:stderr_end]
    return stdout, stderr


@pytest.mark.asyncio
async def test_safe_python_execute_success() -> None:
    """测试受限 Python 工具正常执行。"""
    executor = SafePythonExecutor(
        PythonSafetyConfig(
            default_timeout=3.0,
            max_code_length=2000,
            max_output_length=4000,
        ),
    )
    response = await executor.execute("print('hello-world')")
    text = response.content[0]["text"]
    stdout, stderr = _extract_text_content(text)
    assert "hello-world" in stdout
    assert stderr == ""


@pytest.mark.asyncio
async def test_safe_python_reject_blocked_keyword() -> None:
    """测试受限 Python 工具拦截危险关键字。"""
    executor = SafePythonExecutor(PythonSafetyConfig())
    response = await executor.execute("import os\nprint('x')")
    text = response.content[0]["text"]
    _stdout, stderr = _extract_text_content(text)
    assert "受限" in stderr


@pytest.mark.asyncio
async def test_safe_python_output_truncated() -> None:
    """测试受限 Python 工具输出截断行为。"""
    executor = SafePythonExecutor(
        PythonSafetyConfig(
            default_timeout=3.0,
            max_code_length=4000,
            max_output_length=300,
        ),
    )
    response = await executor.execute("print('a' * 1000)")
    text = response.content[0]["text"]
    assert len(text) <= 350
    assert "已截断" in text


@pytest.mark.asyncio
async def test_safe_python_timeout() -> None:
    """测试受限 Python 工具超时逻辑。"""
    executor = SafePythonExecutor(
        PythonSafetyConfig(
            default_timeout=0.2,
            max_code_length=4000,
            max_output_length=4000,
        ),
    )
    response = await executor.execute("import time\ntime.sleep(1)\nprint('done')")
    text = response.content[0]["text"]
    _stdout, stderr = _extract_text_content(text)
    assert "TimeoutError" in stderr

