"""受限 Python 工具模块。

该模块在 AgentScope 原生执行工具外增加安全限制，包括：
- 代码长度限制
- 高风险关键字/模块拦截
- 执行超时限制
- 输出长度截断
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse, execute_python_code


@dataclass
class PythonSafetyConfig:
    """受限 Python 执行配置。"""

    default_timeout: float = 10.0
    max_code_length: int = 4000
    max_output_length: int = 6000
    blocked_keywords: set[str] = field(
        default_factory=lambda: {
            "subprocess",
            "socket",
            "shutil",
            "pathlib",
            "ctypes",
            "__import__",
            "eval(",
            "exec(",
            "open(",
            "importlib",
            "multiprocessing",
            "threading",
            "requests",
            "httpx",
            "pip ",
            "pip3",
            "os.system",
            "sys.modules",
        },
    )
    blocked_modules: set[str] = field(
        default_factory=lambda: {
            "os",
            "sys",
            "subprocess",
            "socket",
            "pathlib",
            "shutil",
            "ctypes",
            "importlib",
            "multiprocessing",
            "threading",
        },
    )
    blocked_call_names: set[str] = field(
        default_factory=lambda: {
            "open",
            "eval",
            "exec",
            "compile",
            "input",
            "__import__",
        },
    )


class SafePythonExecutor:
    """受限 Python 执行器。

    该类用于封装 AgentScope `execute_python_code`，并在执行前后追加安全治理逻辑。
    """

    def __init__(self, config: PythonSafetyConfig) -> None:
        """初始化受限执行器。

        参数:
            config: 受限执行策略配置。
        """
        self.config = config

    def validate_code(self, code: str) -> str | None:
        """校验输入代码是否满足安全约束。

        参数:
            code: 用户请求执行的 Python 代码。

        返回:
            若合法则返回 None；若不合法则返回错误消息。
        """
        if len(code) > self.config.max_code_length:
            return (
                f"代码长度超过限制，当前长度 {len(code)}，"
                f"最大允许 {self.config.max_code_length}。"
            )

        lowered = code.lower()
        for keyword in self.config.blocked_keywords:
            # 关键字黑名单用于快速拦截明显高风险输入。
            if keyword in lowered:
                return f"代码包含受限关键字: {keyword}"

        try:
            parsed = ast.parse(code)
        except SyntaxError as exc:
            return f"代码语法错误: {exc.msg}"

        for node in ast.walk(parsed):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name.split(".")[0]
                    if module_name in self.config.blocked_modules:
                        return f"代码导入了受限模块: {module_name}"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module_name = node.module.split(".")[0]
                    if module_name in self.config.blocked_modules:
                        return f"代码导入了受限模块: {module_name}"
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in self.config.blocked_call_names:
                        return f"代码调用了受限函数: {node.func.id}"
                elif isinstance(node.func, ast.Attribute):
                    attr_name = node.func.attr
                    if attr_name in {"system", "popen", "remove", "unlink"}:
                        return f"代码调用了受限属性函数: {attr_name}"

        return None

    async def execute(self, code: str, timeout: float | None = None) -> ToolResponse:
        """执行受限 Python 代码。

        参数:
            code: 用户请求执行的 Python 代码。
            timeout: 本次调用超时时间，未传时使用默认值。

        返回:
            ToolResponse: 工具执行结果。
        """
        validation_error = self.validate_code(code)
        if validation_error:
            return self._build_error_response(validation_error)

        resolved_timeout = min(
            timeout if timeout is not None else self.config.default_timeout,
            self.config.default_timeout,
        )
        raw_response = await execute_python_code(
            code=code,
            timeout=resolved_timeout,
        )
        return self._truncate_response(raw_response)

    def _build_error_response(self, error_message: str) -> ToolResponse:
        """构建统一错误响应。

        参数:
            error_message: 错误信息。

        返回:
            ToolResponse: 按 AgentScope 约定封装的错误结果。
        """
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"<returncode>-1</returncode><stdout></stdout><stderr>{error_message}</stderr>",
                ),
            ],
        )

    def _truncate_response(self, response: ToolResponse) -> ToolResponse:
        """对工具结果进行输出截断。

        参数:
            response: 原始工具响应。

        返回:
            ToolResponse: 截断后的工具响应。
        """
        if not response.content:
            return response

        first_block = response.content[0]
        text = first_block.get("text", "") if isinstance(first_block, dict) else ""
        if len(text) <= self.config.max_output_length:
            return response

        truncated_text = self._truncate_tagged_text(text)
        return ToolResponse(
            content=[TextBlock(type="text", text=truncated_text)],
            metadata=response.metadata,
            stream=response.stream,
            is_last=response.is_last,
            is_interrupted=response.is_interrupted,
        )

    def _truncate_tagged_text(self, text: str) -> str:
        """按工具输出标签对文本进行截断。

        参数:
            text: 原始工具输出文本。

        返回:
            str: 截断后的文本。
        """
        pattern = re.compile(
            r"<returncode>(?P<returncode>.*?)</returncode>"
            r"<stdout>(?P<stdout>.*?)</stdout>"
            r"<stderr>(?P<stderr>.*?)</stderr>",
            re.DOTALL,
        )
        matched = pattern.search(text)
        if not matched:
            suffix = "\n[输出已截断]"
            raw_truncated = text[: self.config.max_output_length - len(suffix)]
            return raw_truncated + suffix

        return_code = matched.group("returncode")
        stdout_value = matched.group("stdout")
        stderr_value = matched.group("stderr")

        available = max(self.config.max_output_length - 120, 200)
        stdout_limit = available // 2
        stderr_limit = available - stdout_limit
        trimmed_stdout = self._truncate_plain_text(stdout_value, stdout_limit)
        trimmed_stderr = self._truncate_plain_text(stderr_value, stderr_limit)

        return (
            f"<returncode>{return_code}</returncode>"
            f"<stdout>{trimmed_stdout}</stdout>"
            f"<stderr>{trimmed_stderr}</stderr>"
        )

    def _truncate_plain_text(self, value: str, limit: int) -> str:
        """对普通文本执行截断。

        参数:
            value: 原始文本。
            limit: 最大长度限制。

        返回:
            str: 截断后的文本。
        """
        if len(value) <= limit:
            return value
        return value[: max(limit - 12, 0)] + "...[已截断]"

