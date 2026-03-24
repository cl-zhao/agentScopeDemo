# Context Package 记忆更新设计方案

## 1. 背景与问题

当前引擎是无状态执行引擎。调用方在每次请求时传入完整的 `context_package`，服务端在执行结束后可以返回新的 `next_context_package`。

现阶段服务端只会自动更新：

- `recent_messages`
- `artifacts`

不会自动更新：

- `summary`
- `state`

这会带来三个直接问题：

1. 会话一旦变长，较早历史无法被引擎稳定地沉淀为长期记忆。
2. `state` 完全依赖调用方自行维护，接入复杂度高，而且不同调用方容易出现不一致。
3. `recent_messages` 超出窗口后，旧消息虽然被裁掉，但没有统一、可控、低成本的压缩承接路径。

本设计的目标是让服务端能够高效且精准地更新 `next_context_package` 中的 `summary` 和 `state`，同时保持短会话低成本、长会话可持续。

## 2. 设计目标

1. `recent_messages` 继续承担最近几轮高保真上下文窗口的职责。
2. `summary` 只承担较早历史的压缩记忆职责，不与最近几轮内容重复。
3. `state` 成为结构化事实和任务状态的可信来源。
4. `state` 每轮更新，但优先走确定性逻辑。
5. `summary` 不每轮更新，只在必要时低频触发。
6. 整体设计支持灰度演进、单元测试和集成测试。

## 3. 非目标

1. 不把当前项目改造成服务端持久化记忆系统。
2. 不把任意历史原文长期存储在服务端数据库中。
3. 不允许模型自由生成任意形状的 `state`。
4. 不把原始工具输出直接视为结构化状态。

## 4. 总体设计原则

1. `state` 是结构化真源。
2. `summary` 是较早历史的可读压缩层。
3. `recent_messages` 是最近上下文的高保真真源。
4. 原始工具结果保留在 `artifacts`，提炼后的结论才进入 `state`。
5. 优先使用规则和 reducer，尽量减少模型高频介入。
6. 模型主要用于低频摘要压缩和少量补充提取。
7. 高优先级证据不得被低优先级推断覆盖。

## 5. 目标行为

短会话场景：

- `recent_messages` 可以完整覆盖上下文。
- `summary` 可以为空，或者仅保留很小的背景摘要。
- `state` 每轮增量更新。

长会话场景：

- 最近几轮继续保留在 `recent_messages` 中。
- 被窗口裁掉的旧消息先进入缓冲，再择机压缩进 `summary`。
- `state` 始终保存当前最可操作、最稳定的结构化事实。

## 6. 数据模型设计

### 6.1 ContextPackage 扩展结构

建议将 `ContextPackage` 演进为如下结构：

```json
{
  "version": "1.1",
  "summary": "...",
  "state": {
    "facts": {},
    "task": {},
    "tool_state": {},
    "entities": {}
  },
  "recent_messages": [],
  "artifacts": [],
  "memory_meta": {
    "turn_count": 0,
    "summary_revision": 0,
    "last_summary_turn": 0,
    "summary_buffer": []
  }
}
```

### 6.2 state 固定形状

建议将 `state` 固定为四个主区块：

| 字段 | 作用 | 示例 |
| --- | --- | --- |
| `facts` | 稳定、可复用、可直接消费的事实 | `order_id`、`tracking_no`、`delivery_status`、`last_known_location` |
| `task` | 当前任务状态、未决问题、交互进度 | `intent`、`status`、`pending_questions`、`awaiting_user_input` |
| `tool_state` | 轻量的工具执行状态 | `last_tool_name`、`last_tool_status`、`last_tool_at` |
| `entities` | 多对象场景下的结构化实体 | `orders`、`shipments`、`tickets` |

### 6.3 memory_meta 的职责

`memory_meta` 用于承载引擎内部的记忆更新元信息，不污染业务态 `state`。

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `turn_count` | `int` | 当前 context package 已累计的执行轮数 |
| `summary_revision` | `int` | `summary` 被重压缩的次数 |
| `last_summary_turn` | `int` | 上一次更新 summary 时所在的轮次 |
| `summary_buffer` | `list[ContextMessage]` | 已从 `recent_messages` 溢出、但尚未写入 `summary` 的消息 |

说明：

1. `summary_buffer` 只保存已经离开最近窗口的旧消息。
2. `memory_meta` 必须是可选字段，便于兼容旧版请求。
3. 调用方可以透明透传，无需理解其内部逻辑。

## 7. 组件划分

### 7.1 MemoryUpdateOrchestrator

顶层编排器，负责构建新的 `next_context_package`。

职责：

1. 汇总本轮执行结果和旧上下文。
2. 调用状态提取与归并组件。
3. 更新 `recent_messages`。
4. 管理 `summary_buffer`。
5. 触发或跳过 `summary` 压缩。
6. 组装最终 `next_context_package`。

建议接口：

```python
@dataclass
class MemoryUpdateInput:
    previous: ContextPackage
    current_input: ContextMessage
    final_text: str
    new_artifacts: list[ContextArtifact]
    execution_metadata: dict[str, Any]


class MemoryUpdateOrchestrator:
    async def build_next_package(
        self,
        data: MemoryUpdateInput,
    ) -> ContextPackage: ...
```

### 7.2 StateObservationExtractor

把本轮证据提取成统一的结构化 observation。

职责：

1. 从工具结果中提取结构化事实。
2. 从用户明确表达中提取显式事实。
3. 从 assistant 的明确结论中提取可写回状态的结果。
4. 把不同来源统一规范为同一种 observation 结构。

建议接口：

```python
@dataclass
class StateObservation:
    path: str
    value: Any
    source: Literal["tool", "user", "assistant"]
    confidence: float
    replace: bool = True


class StateObservationExtractor:
    def extract(
        self,
        *,
        previous: ContextPackage,
        current_input: ContextMessage,
        final_text: str,
        new_artifacts: list[ContextArtifact],
    ) -> list[StateObservation]: ...
```

### 7.3 StateReducer

负责把 observation 合并成新的 `state`。

职责：

1. 只允许白名单路径被自动更新。
2. 按固定优先级合并 observation。
3. 处理冲突和不确定写入。
4. 产出 `next_state` 与 `state_delta`。

推荐优先级：

`tool_confirmed > user_explicit > assistant_structured > existing_state`

建议接口：

```python
@dataclass
class StateReduceResult:
    next_state: dict[str, Any]
    state_delta: dict[str, Any]
    conflicts: list[dict[str, Any]]


class StateReducer:
    def reduce(
        self,
        *,
        previous_state: dict[str, Any],
        observations: list[StateObservation],
    ) -> StateReduceResult: ...
```

### 7.4 RecentMessageWindowManager

维护最近几轮高保真消息窗口。

职责：

1. 追加本轮用户输入与最终 assistant 回复。
2. 按配置窗口裁剪消息。
3. 返回被裁掉的旧消息。

建议接口：

```python
@dataclass
class RecentWindowResult:
    recent_messages: list[ContextMessage]
    evicted_messages: list[ContextMessage]


class RecentMessageWindowManager:
    def update(
        self,
        *,
        previous_messages: list[ContextMessage],
        current_input: ContextMessage,
        final_text: str,
    ) -> RecentWindowResult: ...
```

### 7.5 SummaryBufferManager

负责管理 `summary_buffer`，避免每次窗口溢出都立刻重写 `summary`。

职责：

1. 合并历史 `summary_buffer` 和本轮新溢出的消息。
2. 判断是否达到 flush 条件。
3. 支持基于任务里程碑、主题切换等触发立即压缩。

建议接口：

```python
@dataclass
class SummaryBufferDecision:
    next_buffer: list[ContextMessage]
    should_flush: bool
    flush_messages: list[ContextMessage]
    reason: str


class SummaryBufferManager:
    def update(
        self,
        *,
        previous_buffer: list[ContextMessage],
        evicted_messages: list[ContextMessage],
        turn_count: int,
        state_delta: dict[str, Any],
    ) -> SummaryBufferDecision: ...
```

### 7.6 SummaryCompressor

负责把较早历史压缩成新的 `summary`。

职责：

1. 读取旧的 `summary`。
2. 读取待压缩的旧消息。
3. 读取高价值 `state_delta` 和工具结论摘要。
4. 输出新的滚动摘要。
5. 避免重复最近窗口中的内容。

建议接口：

```python
@dataclass
class SummaryCompressionInput:
    previous_summary: str
    flush_messages: list[ContextMessage]
    state_delta: dict[str, Any]
    important_artifacts: list[ContextArtifact]


@dataclass
class SummaryCompressionResult:
    summary: str
    changed: bool


class SummaryCompressor:
    async def compress(
        self,
        data: SummaryCompressionInput,
    ) -> SummaryCompressionResult: ...
```

### 7.7 ArtifactDigestBuilder

负责把大体积工具结果转换为适合摘要压缩的精简事实。

职责：

1. 选取高价值 artifact。
2. 提取工具结果中的关键结论。
3. 防止原始大 payload 进入 summary 压缩过程。

建议接口：

```python
class ArtifactDigestBuilder:
    def build_digest(
        self,
        artifacts: list[ContextArtifact],
    ) -> list[ContextArtifact]: ...
```

## 8. 更新时序设计

建议的更新顺序如下：

1. 收集本轮输入：
   - 旧 `context_package`
   - 当前 `current_input`
   - 最终 assistant 文本
   - 本轮新产生的 artifacts
2. `turn_count + 1`
3. 调用 `StateObservationExtractor`
4. 调用 `StateReducer`，得到 `next_state` 与 `state_delta`
5. 调用 `RecentMessageWindowManager`
6. 把被裁掉的旧消息追加进 `summary_buffer`
7. 调用 `SummaryBufferManager`
8. 若无需 flush：
   - `summary` 保持不变
   - `summary_buffer` 保持更新后的值
9. 若需要 flush：
   - 构造 artifact digest
   - 调用 `SummaryCompressor`
   - 成功后清空或缩小 `summary_buffer`
   - 增加 `summary_revision`
   - 更新 `last_summary_turn`
10. 组装新的 `next_context_package`

关键原因：

1. 必须先更新 `state`，再做 `summary` 压缩，因为 `summary` 应优先基于已规范化的状态结论，而不是纯原始对话。
2. `recent_messages` 与 `summary` 的职责必须分离，避免重复污染。

## 9. summary 更新策略

### 9.1 何时不更新 summary

以下情况不更新 `summary`：

1. `recent_messages` 仍然完整覆盖有效上下文窗口。
2. 本轮没有消息被裁掉。
3. 被裁掉的消息没有长期价值。
4. `summary_buffer` 尚未达到 flush 阈值。

### 9.2 何时更新 summary

以下任一条件满足即可触发 flush：

1. `summary_buffer` 中消息数量达到阈值。
2. `summary_buffer` 总字符数达到阈值。
3. 当前任务到达明确里程碑，比如查询完成、工单关闭。
4. 识别到明显主题切换。
5. 识别到高价值已确认结论。

推荐默认值：

```python
recent_messages_limit = 8
summary_buffer_flush_messages = 4
summary_buffer_flush_chars = 800
```

### 9.3 summary 的输入范围

压缩时应使用：

1. `previous.summary`
2. `flush_messages`
3. `state_delta`
4. 高价值工具结论摘要

压缩时不应使用：

1. 完整 `recent_messages`
2. 原始大体积工具 payload
3. 最近窗口中尚未裁掉的消息

### 9.4 summary 的内容规则

应优先保留：

1. 长期有效背景
2. 已确认事实
3. 已完成事项
4. 未决事项
5. 用户约束和偏好

应避免保留：

1. 最近几轮原文
2. 工具原始输出
3. assistant 的推测性表述
4. 临时过程性噪音

建议输出格式：

```text
[背景]
- 用户正在查询订单 A-1 的物流状态。

[已确认事实]
- 订单号：A-1
- 当前已知物流状态：运输中
- 最近已知位置：上海分拨中心

[已完成事项]
- 已完成订单 A-1 的物流查询。

[未决事项]
- 等待下一次物流节点刷新。
```

## 10. state 更新策略

### 10.1 白名单路径

仅允许白名单路径自动更新，例如：

```text
facts.order_id
facts.tracking_no
facts.delivery_status
facts.last_known_location
task.intent
task.status
task.pending_questions
task.awaiting_user_input
tool_state.last_tool_name
tool_state.last_tool_status
tool_state.last_tool_at
entities.orders.<order_id>
```

### 10.2 冲突处理

若新 observation 与旧高优先级事实冲突：

1. 不立即覆盖。
2. 记录到 reducer 的 `conflicts` 输出中。
3. 视需要转化为 `task.pending_questions`。
4. 后续优先等待工具结果或更强证据确认。

### 10.3 精度保护规则

1. assistant 结论不能引入任意新的顶层字段。
2. 工具确认值可以覆盖弱来源值。
3. 用户显式值可以覆盖 assistant 推断值。
4. 没有更强证据时保留旧值。

## 11. 向后兼容策略

兼容策略建议如下：

1. `memory_meta` 为可选字段，缺失时使用默认值。
2. 输入 `state` 即使不是固定形状，也先做 normalize，再进入 reducer。
3. 保持对 `version="1.0"` 请求的接收能力。
4. 若客户端对未知字段敏感，可通过显式开关决定是否返回 `memory_meta`。

建议默认值：

```python
default_state = {
    "facts": {},
    "task": {},
    "tool_state": {},
    "entities": {},
}

default_memory_meta = {
    "turn_count": 0,
    "summary_revision": 0,
    "last_summary_turn": 0,
    "summary_buffer": [],
}
```

## 12. 失败与降级策略

### 12.1 state 提取失败

若状态提取失败：

1. 保留旧 `state`
2. 继续更新 `recent_messages`
3. 继续保留新 `artifacts`
4. 可在内部 metadata 中记录 warning

### 12.2 summary 压缩失败

若摘要压缩失败：

1. 保留旧 `summary`
2. 保留更新后的 `summary_buffer`
3. 不丢失任何已溢出的旧消息
4. 等待下一轮再次尝试

### 12.3 证据置信度不足

若 observation 置信度不足：

1. 不修改高价值事实
2. 转入 `task.pending_questions`
3. 等待后续工具结果或用户确认

## 13. 测试策略

### 13.1 单元测试

建议补充以下单测：

1. 状态白名单路径更新
2. observation 合并优先级
3. 最近窗口裁剪
4. summary buffer flush 阈值判断
5. 未达阈值时 summary 保持不变
6. 强制 flush 时 summary 正确更新
7. state 冲突处理
8. 旧版 context package normalize 兼容

### 13.2 集成测试

建议补充以下集成测试：

1. 短会话仅更新 `recent_messages` 和 `state`
2. 长会话触发 summary_buffer flush
3. 工具确认值覆盖 assistant 推断值
4. 执行中断时不更新 summary
5. summary 压缩失败时 buffer 不丢失

### 13.3 契约测试

验证返回的 `next_context_package` 满足：

1. 最新轮次消息始终保留在 `recent_messages`
2. 被裁掉的消息不会在未缓冲、未压缩的情况下直接丢失
3. 原始工具输出仍保留在 `artifacts`
4. `state` 始终保持结构化、紧凑、可控

## 14. 分阶段落地建议

### 阶段一

先落确定性路径：

1. 固定 `state` 结构
2. 实现 observation 提取
3. 实现 reducer
4. 实现 recent 窗口管理
5. 实现 summary_buffer，但暂不引入模型摘要压缩

### 阶段二

再引入低频 summary 压缩：

1. flush 规则
2. summary compressor
3. sectioned summary 输出格式

### 阶段三

增强精度和领域能力：

1. assistant 结构化提取白名单控制
2. 冲突转 pending_questions
3. 针对订单、物流、工单等场景的专用 reducer

## 15. 参考伪代码

```python
async def build_next_package(data: MemoryUpdateInput) -> ContextPackage:
    previous = normalize_context_package(data.previous)
    next_turn_count = previous.memory_meta.turn_count + 1

    observations = state_observation_extractor.extract(
        previous=previous,
        current_input=data.current_input,
        final_text=data.final_text,
        new_artifacts=data.new_artifacts,
    )

    reduce_result = state_reducer.reduce(
        previous_state=previous.state,
        observations=observations,
    )

    recent_result = recent_window_manager.update(
        previous_messages=previous.recent_messages,
        current_input=data.current_input,
        final_text=data.final_text,
    )

    buffer_decision = summary_buffer_manager.update(
        previous_buffer=previous.memory_meta.summary_buffer,
        evicted_messages=recent_result.evicted_messages,
        turn_count=next_turn_count,
        state_delta=reduce_result.state_delta,
    )

    next_summary = previous.summary
    next_buffer = buffer_decision.next_buffer
    summary_revision = previous.memory_meta.summary_revision
    last_summary_turn = previous.memory_meta.last_summary_turn

    if buffer_decision.should_flush:
        digest_artifacts = artifact_digest_builder.build_digest(data.new_artifacts)
        compression_result = await summary_compressor.compress(
            SummaryCompressionInput(
                previous_summary=previous.summary,
                flush_messages=buffer_decision.flush_messages,
                state_delta=reduce_result.state_delta,
                important_artifacts=digest_artifacts,
            )
        )
        if compression_result.changed:
            next_summary = compression_result.summary
            next_buffer = []
            summary_revision += 1
            last_summary_turn = next_turn_count

    return ContextPackage(
        version="1.1",
        summary=next_summary,
        state=reduce_result.next_state,
        recent_messages=recent_result.recent_messages,
        artifacts=[*previous.artifacts, *data.new_artifacts],
        memory_meta={
            "turn_count": next_turn_count,
            "summary_revision": summary_revision,
            "last_summary_turn": last_summary_turn,
            "summary_buffer": next_buffer,
        },
    )
```

## 16. 最终建议

推荐实现路径如下：

1. 引入 `memory_meta`
2. 固化 `state` 结构
3. 每轮更新 `state`
4. 持续维护 `recent_messages`
5. 用 `summary_buffer` 吸收被裁掉的旧消息
6. 只在必要时压缩更新 `summary`

该方案可以同时满足：

1. 短会话低成本
2. 长会话可持续
3. 结构化记忆高精度
4. 摘要更新低频且可控
5. 当前项目平滑演进
