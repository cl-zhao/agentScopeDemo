import json

from agentscope.mcp import HttpStatelessClient, MCPToolFunction
from agentscope.tool import Toolkit

from app.config import AppConfig


async def reg_mcp_function_level_usage(toolkit: Toolkit, config: AppConfig, func_name_list: list[str] = None) -> Toolkit:
    """使用函数级别 MCP 工具的示例。"""
    MCP_SERVICES_TRANSPORT = config.mcp_services_transport
    MCP_SERVICES_HOST = config.mcp_services_host
    stateless_client = HttpStatelessClient(
        # 用于标识 MCP 的名称
        name="mcp_services_stateless",
        transport=MCP_SERVICES_TRANSPORT,
        url=MCP_SERVICES_HOST,
    )
    if func_name_list is None:
        # 全部加载
        # 从 MCP 服务器注册所有工具
        await toolkit.register_mcp_client(
            stateless_client,
            # group_name="mcp_services_group_1",  # 可选的组名
        )
    else:
        # 部分加载
        for func_name in func_name_list:
            await _mcp_function_level_usage(toolkit, stateless_client, func_name)

    return toolkit


async def _mcp_function_level_usage(toolkit, stateless_client, func_name):
    func_obj1 = await stateless_client.get_callable_function(
        func_name=func_name,
        # 是否将工具结果包装到 AgentScope 的 ToolResponse 中
        wrap_tool_result=True,
    )
    if not isinstance(func_obj1, MCPToolFunction):
        raise Exception("请检查函数名称是否正确")
    func_obj: MCPToolFunction = func_obj1

    # 您可以获取其名称、描述和 JSON schema
    print("函数名称：", func_obj.name)
    print("函数描述：", func_obj.description)
    print(
        "函数 JSON schema：",
        json.dumps(func_obj.json_schema, indent=4, ensure_ascii=False),
    )

    toolkit.register_tool_function(func_obj)
