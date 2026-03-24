"""确定性的状态规范化与归并辅助工具。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal


_STATE_SECTION_NAMES = ("facts", "task", "tool_state", "entities")
_TOOL_FACT_ALIASES = {
    "order_id": "facts.order_id",
    "orderId": "facts.order_id",
    "tracking_no": "facts.tracking_no",
    "tracking_number": "facts.tracking_no",
    "trackingNumber": "facts.tracking_no",
    "delivery_status": "facts.delivery_status",
    "shipping_status": "facts.delivery_status",
    "logistics_status": "facts.delivery_status",
    "last_known_location": "facts.last_known_location",
    "lastKnownLocation": "facts.last_known_location",
}
_ASSISTANT_LABEL_ALIASES = {
    "delivery status": "facts.delivery_status",
    "last known location": "facts.last_known_location",
    "logistics status": "facts.delivery_status",
    "order id": "facts.order_id",
    "tracking no": "facts.tracking_no",
    "tracking number": "facts.tracking_no",
    "当前位置": "facts.last_known_location",
    "快递单号": "facts.tracking_no",
    "最新位置": "facts.last_known_location",
    "物流单号": "facts.tracking_no",
    "物流状态": "facts.delivery_status",
    "订单号": "facts.order_id",
    "运单号": "facts.tracking_no",
    "配送状态": "facts.delivery_status",
}
_USER_FIELD_PATTERNS = (
    (
        "facts.order_id",
        (
            re.compile(
                r"\border(?:\s+id)?\s*(?:is|=|:)\s*([A-Za-z0-9][A-Za-z0-9-]{1,63})\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?:订单号|订单)\s*(?:是|为|[:：])\s*([A-Za-z0-9][A-Za-z0-9-]{1,63})",
            ),
        ),
    ),
    (
        "facts.tracking_no",
        (
            re.compile(
                r"\btracking(?:\s+number|\s+no\.?)?\s*(?:is|=|:)\s*([A-Za-z0-9][A-Za-z0-9-]{3,63})\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?:运单号|物流单号|快递单号)\s*(?:是|为|[:：])\s*([A-Za-z0-9][A-Za-z0-9-]{3,63})",
            ),
        ),
    ),
)
_CONFLICT_SENSITIVE_PATHS = {
    "facts.order_id",
    "facts.tracking_no",
    "facts.delivery_status",
    "facts.last_known_location",
}
_USER_OVERRIDE_PATHS = {
    "facts.order_id",
    "facts.tracking_no",
}
_SOURCE_PRIORITY = {"assistant": 1, "user": 2, "tool": 3}


def normalize_context_state(state: dict[str, Any]) -> dict[str, Any]:
    """在保留旧键的同时，确保预期的状态分区存在。"""

    normalized = dict(state) if isinstance(state, dict) else {}
    for section_name in _STATE_SECTION_NAMES:
        section_value = normalized.get(section_name)
        normalized[section_name] = dict(section_value) if isinstance(section_value, dict) else {}
    return normalized


@dataclass(frozen=True)
class StateObservation:
    """从执行证据中提取出的单条规范化状态候选更新。"""

    path: str
    value: Any
    source: Literal["tool", "user", "assistant"]
    confidence: float
    replace: bool = True


@dataclass
class StateReduceResult:
    """归并后的状态，以及结构化增量与冲突信息。"""

    next_state: dict[str, Any]
    state_delta: dict[str, Any] = field(default_factory=dict)
    conflicts: list[dict[str, Any]] = field(default_factory=list)


class StateObservationExtractor:
    """从 artifacts 和消息中提取确定性的状态观察值。"""

    def extract(
        self,
        *,
        current_input: Any,
        final_text: str,
        new_artifacts: list[Any],
    ) -> list[StateObservation]:
        """汇总当前轮次消息及工具 artifact 中的状态观察值。"""
        observations: list[StateObservation] = []
        observations.extend(self._extract_user_facts(current_input))
        observations.extend(self._extract_assistant_facts(final_text))

        if new_artifacts:
            latest_artifact = new_artifacts[-1]
            if latest_artifact.tool_name:
                observations.append(
                    StateObservation(
                        path="tool_state.last_tool_name",
                        value=latest_artifact.tool_name,
                        source="tool",
                        confidence=1.0,
                    )
                )
            observations.append(
                StateObservation(
                    path="tool_state.last_tool_status",
                    value="completed",
                    source="tool",
                    confidence=1.0,
                )
            )
            if latest_artifact.created_at is not None:
                observations.append(
                    StateObservation(
                        path="tool_state.last_tool_at",
                        value=latest_artifact.created_at.isoformat(),
                        source="tool",
                        confidence=1.0,
                    )
                )

        for artifact in new_artifacts:
            observations.extend(self._extract_tool_facts(artifact.content))

        return observations

    def _extract_tool_facts(self, payload: Any) -> list[StateObservation]:
        """从单个工具载荷树中提取已知事实别名。"""
        observations: list[StateObservation] = []
        self._walk_payload(payload, observations)
        return observations

    def _extract_user_facts(self, current_input: Any) -> list[StateObservation]:
        """从当前用户输入中提取显式声明的标识信息。"""
        role = getattr(current_input, "role", None)
        content = getattr(current_input, "content", None)
        if role != "user" or not isinstance(content, str):
            return []

        observations: list[StateObservation] = []
        for path, patterns in _USER_FIELD_PATTERNS:
            value = self._extract_first_pattern_value(content, patterns)
            if value is None:
                continue
            observations.append(
                StateObservation(
                    path=path,
                    value=value,
                    source="user",
                    confidence=0.95,
                )
            )
        return observations

    def _extract_assistant_facts(self, final_text: str) -> list[StateObservation]:
        """从 assistant 最终文本中保守提取标签-值形式的事实。"""
        if not isinstance(final_text, str) or not final_text.strip():
            return []

        observations: list[StateObservation] = []
        seen_paths: set[str] = set()
        for raw_line in final_text.splitlines():
            match = re.match(r"^\s*([^:：]{2,40})\s*[:：]\s*(.+?)\s*$", raw_line)
            if match is None:
                continue
            label = self._normalize_label(match.group(1))
            path = _ASSISTANT_LABEL_ALIASES.get(label)
            if path is None or path in seen_paths:
                continue
            value = self._normalize_scalar_text(match.group(2))
            if value is None:
                continue
            seen_paths.add(path)
            observations.append(
                StateObservation(
                    path=path,
                    value=value,
                    source="assistant",
                    confidence=0.7,
                )
            )
        return observations

    def _walk_payload(self, payload: Any, observations: list[StateObservation]) -> None:
        """遍历嵌套载荷结构并记录已知的标量事实别名。"""
        if isinstance(payload, dict):
            for key, value in payload.items():
                path = _TOOL_FACT_ALIASES.get(key)
                if path is not None and self._is_scalar(value):
                    observations.append(
                        StateObservation(
                            path=path,
                            value=value,
                            source="tool",
                            confidence=1.0,
                        )
                    )
                self._walk_payload(value, observations)
            return

        if isinstance(payload, list):
            for item in payload:
                self._walk_payload(item, observations)

    def _extract_first_pattern_value(
        self,
        text: str,
        patterns: tuple[re.Pattern[str], ...],
    ) -> str | None:
        """返回一组正则模式命中的第一个规范化值。"""
        for pattern in patterns:
            match = pattern.search(text)
            if match is None:
                continue
            value = self._normalize_scalar_text(match.group(1))
            if value is not None:
                return value
        return None

    def _normalize_label(self, label: str) -> str:
        """在匹配已知事实路径前先规范化 assistant 标签。"""
        normalized = re.sub(r"[_-]+", " ", label.strip().lower())
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    def _normalize_scalar_text(self, value: str) -> str | None:
        """裁剪提取出的标量值，并过滤空结果。"""
        normalized = value.strip().rstrip(" ,.;:，。；：")
        if not normalized:
            return None
        return normalized

    @staticmethod
    def _is_scalar(value: Any) -> bool:
        """判断一个值是否可以直接作为事实标量存储。"""
        return isinstance(value, (str, int, float, bool))


class StateReducer:
    """按确定性优先级将观察值归并进规范化状态。"""

    def __init__(self, *, pending_question_limit: int = 6) -> None:
        """配置最多保留多少条未解决的冲突确认问题。"""
        self._pending_question_limit = pending_question_limit

    def reduce(
        self,
        *,
        previous_state: dict[str, Any],
        observations: list[StateObservation],
    ) -> StateReduceResult:
        """将观察值应用到状态中，并把未解决冲突写入任务状态。"""
        next_state = normalize_context_state(previous_state)
        state_delta: dict[str, Any] = {}
        conflicts: list[dict[str, Any]] = []
        chosen: dict[str, StateObservation] = {}

        for observation in observations:
            if not self._is_allowed_path(observation.path):
                continue
            current = chosen.get(observation.path)
            if current is None or self._wins(observation, current):
                chosen[observation.path] = observation

        previous_pending_questions = self._normalize_pending_questions(
            next_state["task"].get("pending_questions"),
        )
        pending_questions = list(previous_pending_questions)

        for path, observation in chosen.items():
            pending_questions = self._resolve_pending_questions(
                pending_questions,
                path=path,
                observation=observation,
            )
            previous_value = self._get_path(next_state, path)
            if previous_value == observation.value:
                continue
            if previous_value is not None and self._should_hold_for_clarification(
                path=path,
                observation=observation,
            ):
                question = self._build_pending_question(
                    path=path,
                    previous_value=previous_value,
                    observation=observation,
                )
                pending_questions = self._append_pending_question(pending_questions, question)
                conflicts.append(
                    {
                        "path": path,
                        "existing_value": previous_value,
                        "candidate_value": observation.value,
                        "source": observation.source,
                    }
                )
                continue
            self._set_path(next_state, path, observation.value)
            self._set_path(state_delta, path, observation.value)

        if pending_questions != previous_pending_questions:
            self._set_path(state_delta, "task.pending_questions", pending_questions)
        if pending_questions or "pending_questions" in next_state["task"]:
            next_state["task"]["pending_questions"] = pending_questions

        return StateReduceResult(
            next_state=next_state,
            state_delta=state_delta,
            conflicts=conflicts,
        )

    def _wins(self, candidate: StateObservation, existing: StateObservation) -> bool:
        """根据来源优先级和置信度选择更强的观察值。"""
        candidate_priority = _SOURCE_PRIORITY[candidate.source]
        existing_priority = _SOURCE_PRIORITY[existing.source]
        if candidate_priority != existing_priority:
            return candidate_priority > existing_priority
        return candidate.confidence >= existing.confidence

    def _should_hold_for_clarification(
        self,
        *,
        path: str,
        observation: StateObservation,
    ) -> bool:
        """判断冲突观察值是否应转为待确认问题。"""
        if path not in _CONFLICT_SENSITIVE_PATHS:
            return False
        if observation.source == "tool":
            return False
        if observation.source == "user" and path in _USER_OVERRIDE_PATHS:
            return False
        return True

    def _build_pending_question(
        self,
        *,
        path: str,
        previous_value: Any,
        observation: StateObservation,
    ) -> str:
        """为冲突事实构造一条可读的澄清问题。"""
        field_name = path.split(".")[-1]
        return (
            f"Confirm {field_name}: existing '{previous_value}' conflicts with "
            f"{observation.source} value '{observation.value}'."
        )

    def _append_pending_question(
        self,
        pending_questions: list[str],
        question: str,
    ) -> list[str]:
        """在遵守上限的前提下追加唯一的待确认问题。"""
        if self._pending_question_limit <= 0:
            return []
        if question not in pending_questions:
            pending_questions.append(question)
        if len(pending_questions) <= self._pending_question_limit:
            return pending_questions
        return pending_questions[-self._pending_question_limit :]

    def _resolve_pending_questions(
        self,
        pending_questions: list[str],
        *,
        path: str,
        observation: StateObservation,
    ) -> list[str]:
        """移除已被更强观察值解决的待确认问题。"""
        if observation.source == "tool":
            field_name = path.split(".")[-1]
            prefix = f"Confirm {field_name}:"
            return [item for item in pending_questions if not item.startswith(prefix)]
        if observation.source == "user" and path in _USER_OVERRIDE_PATHS:
            field_name = path.split(".")[-1]
            prefix = f"Confirm {field_name}:"
            return [item for item in pending_questions if not item.startswith(prefix)]
        return pending_questions

    def _normalize_pending_questions(self, value: Any) -> list[str]:
        """将待确认问题状态规范化为干净的字符串列表。"""
        if not isinstance(value, list):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    def _is_allowed_path(self, path: str) -> bool:
        """判断观察路径是否指向受支持的状态分区。"""
        parts = path.split(".")
        return len(parts) >= 2 and parts[0] in _STATE_SECTION_NAMES

    def _get_path(self, payload: dict[str, Any], path: str) -> Any:
        """从嵌套字典中读取一条点分路径。"""
        current: Any = payload
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    def _set_path(self, payload: dict[str, Any], path: str, value: Any) -> None:
        """向嵌套字典写入一条点分路径。"""
        current = payload
        parts = path.split(".")
        for part in parts[:-1]:
            next_item = current.get(part)
            if not isinstance(next_item, dict):
                next_item = {}
                current[part] = next_item
            current = next_item
        current[parts[-1]] = value
