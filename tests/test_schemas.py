"""schemas 模块单元测试。"""

from __future__ import annotations

from app.schemas import ChatStreamRequest, ResponseMode, TaskResultSchema


def test_chat_stream_request_default_mode() -> None:
    """测试 ChatStreamRequest 默认响应模式。"""
    request = ChatStreamRequest(message="hello", access_param="opaque-token")
    assert request.response_mode == ResponseMode.TEXT


def test_task_result_schema_fields() -> None:
    """测试 TaskResultSchema 字段完整性。"""
    result = TaskResultSchema(
        summary="任务完成",
        actions=["动作1"],
        risks=["风险1"],
        next_steps=["下一步1"],
    )
    dumped = result.model_dump()
    assert dumped["summary"] == "任务完成"
    assert dumped["actions"] == ["动作1"]
    assert dumped["risks"] == ["风险1"]
    assert dumped["next_steps"] == ["下一步1"]

