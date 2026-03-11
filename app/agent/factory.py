"""智能体工厂模块。

该模块用于构建 ReActAgent，并统一注册模型、格式化器和工具集。
"""

from __future__ import annotations

import ast
import json
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agentscope.agent import ReActAgent
from agentscope.formatter import OpenAIChatFormatter
from agentscope.memory import InMemoryMemory
from agentscope.message import TextBlock
from agentscope.model import OpenAIChatModel
from agentscope.tool import ToolResponse, Toolkit

from app.config import AppConfig
from app.tools import SafePythonExecutor


class SafeExpressionEvaluator:
    """安全表达式计算器。

    该类仅允许执行数学表达式相关 AST 节点，避免任意代码执行风险。
    """

    def evaluate(self, expression: str) -> float:
        """计算数学表达式。

        参数:
            expression: 待计算表达式，如 `1 + 2 * (3 - 4)`。

        返回:
            float: 表达式结果。
        """
        parsed = ast.parse(expression, mode="eval")
        return float(self._eval_node(parsed.body))

    def _eval_node(self, node: ast.AST) -> float:
        """递归计算 AST 节点。

        参数:
            node: 当前 AST 节点。

        返回:
            float: 当前节点计算结果。

        异常:
            ValueError: 当节点类型不在白名单时抛出。
        """
        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Pow):
                return left**right
            if isinstance(node.op, ast.Mod):
                return left % right
            raise ValueError("不支持的二元运算符。")

        if isinstance(node, ast.UnaryOp):
            value = self._eval_node(node.operand)
            if isinstance(node.op, ast.UAdd):
                return +value
            if isinstance(node.op, ast.USub):
                return -value
            raise ValueError("不支持的一元运算符。")

        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)

        raise ValueError("表达式包含不安全或不支持的语法。")


class AgentFactory:
    """ReActAgent 构建工厂。

    该工厂负责创建可复用的会话智能体实例，并注入统一工具集。
    """

    def __init__(self, config: AppConfig, python_executor: SafePythonExecutor) -> None:
        """初始化工厂。

        参数:
            config: 应用配置。
            python_executor: 受限 Python 执行器实例。
        """
        self.config = config
        self.python_executor = python_executor
        self.expression_evaluator = SafeExpressionEvaluator()

    async def get_current_time(self, timezone_name: str = "UTC") -> ToolResponse:
        """获取指定时区的当前时间。

        参数:
            timezone_name: IANA 时区名称，默认 UTC。

        返回:
            ToolResponse: 当前时间文本。
        """
        try:
            now = datetime.now(ZoneInfo(timezone_name))
        except ZoneInfoNotFoundError:
            now = datetime.now(ZoneInfo("UTC"))
            timezone_name = "UTC"

        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        f"当前时间({timezone_name})为 "
                        f"{now.isoformat(timespec='seconds')}。"
                    ),
                ),
            ],
        )

    async def evaluate_expression(self, expression: str) -> ToolResponse:
        """计算数学表达式。

        参数:
            expression: 用户输入表达式。

        返回:
            ToolResponse: 计算结果或错误信息。
        """
        try:
            result = self.expression_evaluator.evaluate(expression)
            content_text = json.dumps(
                {"expression": expression, "result": result},
                ensure_ascii=False,
            )
            return ToolResponse(
                content=[TextBlock(type="text", text=content_text)],
            )
        except Exception as exc:  # noqa: BLE001 - 需要转换为工具可读错误输出
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"表达式计算失败: {exc}",
                    ),
                ],
            )

    async def safe_execute_python(self, code: str, timeout: float = 10.0) -> ToolResponse:
        """执行受限 Python 代码。

        参数:
            code: Python 代码字符串。
            timeout: 期望超时时间（秒）。

        返回:
            ToolResponse: 执行输出。
        """
        return await self.python_executor.execute(code=code, timeout=timeout)

    def create_agent(self) -> ReActAgent:
        """构建 ReActAgent 实例。

        返回:
            ReActAgent: 完整初始化后的智能体。
        """
        generate_kwargs: dict[str, object] = {
            "temperature": self.config.model_temperature,
            # 模型层面同时打开并行工具调用参数。
            "parallel_tool_calls": True,
        }
        if self.config.model_max_tokens is not None:
            generate_kwargs["max_tokens"] = self.config.model_max_tokens

        model = OpenAIChatModel(
            model_name=self.config.ark_model,
            api_key=self.config.ark_api_key,
            stream=True,
            client_kwargs={
                "base_url": self.config.ark_base_url,
            },
            generate_kwargs=generate_kwargs,
        )

        toolkit = Toolkit()
        toolkit.register_tool_function(self.get_current_time)
        toolkit.register_tool_function(self.evaluate_expression)
        toolkit.register_tool_function(self.safe_execute_python)

        agent = ReActAgent(
            name="ReActAssistant",
            sys_prompt=self.config.system_prompt,
            model=model,
            formatter=OpenAIChatFormatter(),
            toolkit=toolkit,
            memory=InMemoryMemory(),
            parallel_tool_calls=True,
        )

        # HTTP 服务模式下关闭终端打印，避免日志污染。
        agent.set_console_output_enabled(False)
        return agent

