from __future__ import annotations

from datetime import datetime, timezone

from app.execution.context_package import ContextPackageUpdater, build_tool_artifact
from app.schemas import ContextArtifact, ContextMemoryMeta, ContextMessage, ContextPackage


def test_build_next_context_package_appends_latest_turn() -> None:
    updater = ContextPackageUpdater(
        recent_message_limit=4,
        summary_buffer_flush_messages=4,
        summary_buffer_flush_chars=800,
    )
    next_package = updater.build_next_package(
        previous=ContextPackage(
            summary="older summary",
            recent_messages=[ContextMessage(role="user", content="old question")],
        ),
        current_input=ContextMessage(role="user", content="new question"),
        final_text="new answer",
        artifacts=[],
    )

    assert next_package.recent_messages[-2].content == "new question"
    assert next_package.recent_messages[-1].content == "new answer"


def test_build_artifacts_keeps_raw_tool_output() -> None:
    artifact = build_tool_artifact(
        tool_event={
            "tool_id": "tool-1",
            "tool_name": "execute_sql_query",
            "status": "completed",
            "output": [{"type": "text", "text": "{\"rows\":[{\"id\":1}]}"}],
        }
    )

    assert artifact.tool_name == "execute_sql_query"
    assert artifact.content[0]["text"].startswith("{\"rows\"")


def test_build_next_context_package_normalizes_state_and_tracks_turn_count() -> None:
    updater = ContextPackageUpdater(
        recent_message_limit=4,
        summary_buffer_flush_messages=4,
        summary_buffer_flush_chars=800,
    )
    next_package = updater.build_next_package(
        previous=ContextPackage(
            summary="older summary",
            state={"legacy_key": "legacy-value"},
            memory_meta=ContextMemoryMeta(turn_count=2),
        ),
        current_input=ContextMessage(role="user", content="new question"),
        final_text="new answer",
        artifacts=[],
    )

    assert next_package.state["facts"] == {}
    assert next_package.state["task"] == {}
    assert next_package.state["tool_state"] == {}
    assert next_package.state["entities"] == {}
    assert next_package.state["legacy_key"] == "legacy-value"
    assert next_package.memory_meta.turn_count == 3


def test_build_next_context_package_extracts_known_facts_from_tool_artifacts() -> None:
    updater = ContextPackageUpdater(
        recent_message_limit=4,
        summary_buffer_flush_messages=4,
        summary_buffer_flush_chars=800,
    )
    next_package = updater.build_next_package(
        previous=ContextPackage(),
        current_input=ContextMessage(role="user", content="check status"),
        final_text="done",
        artifacts=[
            ContextArtifact(
                id="tool-1",
                type="tool_result",
                tool_name="lookup_order",
                content={
                    "order_id": "A-1",
                    "delivery_status": "in_transit",
                    "last_known_location": "Shanghai sorting center",
                },
                importance="high",
                created_at=datetime(2026, 3, 24, 8, 0, tzinfo=timezone.utc),
            )
        ],
    )

    assert next_package.state["facts"]["order_id"] == "A-1"
    assert next_package.state["facts"]["delivery_status"] == "in_transit"
    assert next_package.state["facts"]["last_known_location"] == "Shanghai sorting center"
    assert next_package.state["tool_state"]["last_tool_name"] == "lookup_order"
    assert next_package.state["tool_state"]["last_tool_status"] == "completed"


def test_build_next_context_package_extracts_user_declared_order_and_tracking_ids() -> None:
    updater = ContextPackageUpdater(
        recent_message_limit=4,
        summary_buffer_flush_messages=4,
        summary_buffer_flush_chars=800,
    )
    next_package = updater.build_next_package(
        previous=ContextPackage(),
        current_input=ContextMessage(
            role="user",
            content="order id is A-1 and tracking number is SF123456789CN",
        ),
        final_text="I will check it now.",
        artifacts=[],
    )

    assert next_package.state["facts"]["order_id"] == "A-1"
    assert next_package.state["facts"]["tracking_no"] == "SF123456789CN"


def test_build_next_context_package_extracts_labeled_assistant_facts() -> None:
    updater = ContextPackageUpdater(
        recent_message_limit=4,
        summary_buffer_flush_messages=4,
        summary_buffer_flush_chars=800,
    )
    next_package = updater.build_next_package(
        previous=ContextPackage(),
        current_input=ContextMessage(role="user", content="check shipping"),
        final_text=(
            "Order ID: A-1\n"
            "Tracking Number: SF123456789CN\n"
            "Delivery Status: in_transit\n"
            "Last Known Location: Shanghai sorting center"
        ),
        artifacts=[],
    )

    assert next_package.state["facts"]["order_id"] == "A-1"
    assert next_package.state["facts"]["tracking_no"] == "SF123456789CN"
    assert next_package.state["facts"]["delivery_status"] == "in_transit"
    assert next_package.state["facts"]["last_known_location"] == "Shanghai sorting center"


def test_build_next_context_package_routes_conflicting_assistant_fact_to_pending_questions() -> None:
    updater = ContextPackageUpdater(
        recent_message_limit=4,
        summary_buffer_flush_messages=4,
        summary_buffer_flush_chars=800,
    )
    next_package = updater.build_next_package(
        previous=ContextPackage(
            state={
                "facts": {"delivery_status": "in_transit"},
                "task": {"pending_questions": []},
            }
        ),
        current_input=ContextMessage(role="user", content="check latest status"),
        final_text="Delivery Status: delivered",
        artifacts=[],
    )

    assert next_package.state["facts"]["delivery_status"] == "in_transit"
    assert next_package.state["task"]["pending_questions"] == [
        "Confirm delivery_status: existing 'in_transit' conflicts with assistant value 'delivered'."
    ]


def test_build_next_context_package_tool_result_resolves_matching_pending_question() -> None:
    updater = ContextPackageUpdater(
        recent_message_limit=4,
        summary_buffer_flush_messages=4,
        summary_buffer_flush_chars=800,
    )
    next_package = updater.build_next_package(
        previous=ContextPackage(
            state={
                "facts": {"delivery_status": "in_transit"},
                "task": {
                    "pending_questions": [
                        "Confirm delivery_status: existing 'in_transit' conflicts with assistant value 'delivered'."
                    ]
                },
            }
        ),
        current_input=ContextMessage(role="user", content="refresh status"),
        final_text="Done.",
        artifacts=[
            ContextArtifact(
                id="tool-1",
                type="tool_result",
                tool_name="lookup_order",
                content={"delivery_status": "delivered"},
                importance="high",
                created_at=datetime(2026, 3, 24, 8, 0, tzinfo=timezone.utc),
            )
        ],
    )

    assert next_package.state["facts"]["delivery_status"] == "delivered"
    assert next_package.state["task"]["pending_questions"] == []


def test_build_next_context_package_moves_evicted_recent_messages_to_summary_buffer() -> None:
    updater = ContextPackageUpdater(
        recent_message_limit=4,
        summary_buffer_flush_messages=10,
        summary_buffer_flush_chars=100,
    )
    next_package = updater.build_next_package(
        previous=ContextPackage(
            summary="older summary",
            recent_messages=[
                ContextMessage(role="user", content="u1"),
                ContextMessage(role="assistant", content="a1"),
                ContextMessage(role="user", content="u2"),
                ContextMessage(role="assistant", content="a2"),
            ],
            memory_meta=ContextMemoryMeta(
                turn_count=1,
                summary_revision=1,
                last_summary_turn=1,
                summary_buffer=[ContextMessage(role="user", content="buffered")],
            ),
        ),
        current_input=ContextMessage(role="user", content="u3"),
        final_text="a3",
        artifacts=[],
    )

    assert [message.content for message in next_package.recent_messages] == ["u2", "a2", "u3", "a3"]
    assert [message.content for message in next_package.memory_meta.summary_buffer] == ["buffered", "u1", "a1"]
    assert next_package.summary == "older summary"
    assert next_package.memory_meta.summary_revision == 1
    assert next_package.memory_meta.last_summary_turn == 1


def test_build_next_context_package_flushes_summary_buffer_into_sectioned_summary() -> None:
    updater = ContextPackageUpdater(
        recent_message_limit=4,
        summary_buffer_flush_messages=4,
        summary_buffer_flush_chars=800,
        summary_max_items_per_section=4,
        summary_message_snippet_length=40,
        summary_max_length=1200,
    )
    next_package = updater.build_next_package(
        previous=ContextPackage(
            summary="[背景]\n- 用户正在查询订单历史\n",
            recent_messages=[
                ContextMessage(role="user", content="我想查订单 A-1"),
                ContextMessage(role="assistant", content="好的，我来查询"),
                ContextMessage(role="user", content="还有物流状态"),
                ContextMessage(role="assistant", content="继续为你查询"),
            ],
            memory_meta=ContextMemoryMeta(
                turn_count=3,
                summary_revision=1,
                last_summary_turn=2,
                summary_buffer=[
                    ContextMessage(role="user", content="之前问过 A-1 的进度"),
                    ContextMessage(role="assistant", content="之前已经查到过一次"),
                ],
            ),
        ),
        current_input=ContextMessage(role="user", content="再帮我看下最新节点"),
        final_text="最新节点已经更新",
        artifacts=[
            ContextArtifact(
                id="tool-1",
                type="tool_result",
                tool_name="lookup_order",
                content={
                    "order_id": "A-1",
                    "delivery_status": "in_transit",
                },
                importance="high",
                created_at=datetime(2026, 3, 24, 8, 0, tzinfo=timezone.utc),
            )
        ],
    )

    assert "[背景]" in next_package.summary
    assert "[已确认事实]" in next_package.summary
    assert "订单历史" in next_package.summary
    assert "order_id: A-1" in next_package.summary
    assert "delivery_status: in_transit" in next_package.summary
    assert next_package.memory_meta.summary_buffer == []
    assert next_package.memory_meta.summary_revision == 2
    assert next_package.memory_meta.last_summary_turn == 4


def test_build_next_context_package_uses_configured_summary_snippet_length() -> None:
    updater = ContextPackageUpdater(
        recent_message_limit=2,
        summary_buffer_flush_messages=1,
        summary_buffer_flush_chars=10,
        summary_max_items_per_section=4,
        summary_message_snippet_length=12,
        summary_max_length=1200,
    )
    next_package = updater.build_next_package(
        previous=ContextPackage(
            recent_messages=[
                ContextMessage(role="user", content="这是一条非常非常长的历史消息，需要被截断"),
                ContextMessage(role="assistant", content="这是一条同样很长的回复消息"),
            ]
        ),
        current_input=ContextMessage(role="user", content="新问题"),
        final_text="新答案",
        artifacts=[],
    )

    assert "..." in next_package.summary
