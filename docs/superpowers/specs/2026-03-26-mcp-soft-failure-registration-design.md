# MCP 注册软失败降级设计

## 1. 背景

当前工程会在 Agent 初始化阶段注册 MCP 工具。注册入口位于 `app/agent/factory.py`，核心逻辑位于 `app/agent/mcp_registry.py`。

现状中，MCP 注册被视为硬依赖：

- MCP 服务不在线时，注册阶段直接抛错。
- MCP 服务地址不可达、握手失败或网络异常时，注册阶段直接抛错。
- 按函数名注册时，如果函数名写错或返回对象异常，也会直接抛错。

由于这些异常发生在 Agent 创建阶段，而不是工具真正被调用阶段，因此它们会直接中断整次请求。这与 MCP 作为外部依赖的稳定性特征不匹配，也会降低主流程的可用性。

## 2. 问题定义

当前实现的核心问题不是“某个 MCP 调用失败”，而是“某个 MCP 无法注册时，整个请求被提前打断”。

这会带来以下后果：

- 单个外部 MCP 服务故障会影响整个 Agent 主流程。
- 即使本地工具和其他能力完全可用，请求仍然直接失败。
- 配置错误和临时网络抖动没有被限制在 MCP 边界内，而是向上冒泡成全局失败。
- 控制台缺少统一、可检索的 warning 信息，问题定位依赖异常堆栈，噪音较大。

## 3. 设计目标

本次设计目标如下：

- 将 MCP 注册阶段改为“软失败”模式。
- 当 MCP 服务不在线、连接失败、网络异常时，跳过该 MCP 注册，不中断主请求。
- 当按函数名注册时，如果函数名错误或返回对象不是预期类型，也跳过该函数，不中断主请求。
- 在控制台输出明确 warning，帮助排查被跳过的 MCP。
- 保持 Agent 创建主流程稳定，本地工具和已成功注册的工具仍可正常使用。
- 为后续补充监控、指标或结构化启动摘要保留扩展空间。

## 4. 非目标

本设计不解决以下问题：

- 不负责自动重试离线的 MCP 服务。
- 不负责在请求执行过程中动态重新探测已跳过的 MCP。
- 不负责对调用阶段的 MCP 运行错误做语义改造。
- 不引入新的配置开关来切换“严格模式”和“宽松模式”。
- 不改变 `factory.py` 的主创建流程，只调整 MCP 注册边界的失败语义。

## 5. 核心设计

### 5.1 失败语义调整

将 `app/agent/mcp_registry.py` 从“失败即抛出”改为“失败即 warning 并跳过”。

适用范围包括：

- `toolkit.register_mcp_client(...)` 失败。
- `stateless_client.get_callable_function(...)` 失败。
- 返回对象不是 `MCPToolFunction`。
- 其他由 MCP 注册路径抛出的异常。

在这些场景下：

- 不再向上抛出异常打断 Agent 初始化。
- 当前失败的 MCP 或当前失败的函数会被跳过。
- 函数返回的 `toolkit` 仍然保持可用状态并继续后续流程。

### 5.2 全量注册行为

当 `func_name_list is None` 时，表示走整组 MCP 注册：

- 调用 `toolkit.register_mcp_client(stateless_client)`。
- 如果成功，则整组 MCP 工具正常接入。
- 如果失败，则整组 MCP 跳过，并输出一条 warning。
- Agent 继续创建，不因该 MCP 失败而中断。

该模式下失败粒度是“整组服务”。

### 5.3 按函数名注册行为

当 `func_name_list` 非空时，表示按函数名逐个注册：

- 对每一个 `func_name` 独立执行加载与注册。
- 每个函数单独 `try/except`。
- 单个函数失败时，仅跳过该函数，不影响其他函数继续注册。
- 即使函数名写错，也视为软失败并 warning，不抛异常。

该模式下失败粒度是“单个函数”。

### 5.4 返回值设计

`reg_mcp_function_level_usage(...)` 继续返回 `toolkit`，以保持现有调用接口兼容。

同时建议新增轻量级结构化结果统计能力，但不要求调用方必须消费，例如：

- 尝试注册的模式：全量或按函数名。
- 成功注册的函数数量。
- 跳过的函数数量。
- 跳过原因摘要。

如本轮实现成本较高，可先在模块内部构造并仅用于日志，不强制外露给 `factory.py`。

## 6. 日志设计

### 6.1 日志方式

`app/agent/mcp_registry.py` 不再使用零散 `print`，改为模块级 `logger` 输出 warning 和必要的 info/debug。

建议：

- `warning` 用于注册失败并发生降级。
- `info` 或 `debug` 用于注册成功时的补充信息。

### 6.2 Warning 内容

warning 至少应包含以下信息：

- MCP 名称，例如 `mcp_services_stateless`。
- `transport`
- `host`
- 当前模式：全量注册或按函数名注册。
- 函数名（如果是单函数注册路径）。
- 异常摘要。

示例语义：

> MCP registration skipped because the remote service is unavailable.

或：

> MCP function registration skipped because the configured function name is invalid.

最终实现中不要求完全照抄以上文本，但必须让调用方能直接看出：

- 是哪一个 MCP 被跳过。
- 为什么被跳过。
- 本次跳过不会中断请求。

## 7. 调用方边界

`app/agent/factory.py` 不承担 MCP 降级判断逻辑。

调用方边界如下：

- 继续正常调用 `await reg_mcp_function_level_usage(toolkit, self.config)`。
- 默认信任该函数具备软失败能力。
- 不在 `factory.py` 再包一层宽泛的 `try/except` 吞掉所有错误。

原因是：

- 降级逻辑应当聚合在 MCP 注册模块内部，而不是分散在调用方。
- 这样可以保证全量注册与按函数名注册共用一套容错语义。
- `factory.py` 继续保持“组装 agent”的单一职责。

## 8. 预期行为矩阵

| 场景 | 旧行为 | 新行为 |
| --- | --- | --- |
| MCP 服务离线 | 抛异常，中断请求 | warning，跳过该 MCP，请求继续 |
| MCP 地址不可达/连接失败 | 抛异常，中断请求 | warning，跳过该 MCP，请求继续 |
| 网络抖动/握手异常 | 抛异常，中断请求 | warning，跳过该 MCP，请求继续 |
| 函数名写错 | 抛异常，中断请求 | warning，跳过该函数，请求继续 |
| 返回对象不是 `MCPToolFunction` | 抛异常，中断请求 | warning，跳过该函数，请求继续 |
| 其他本地工具注册正常 | 可能被连带中断 | 不受影响，继续可用 |

## 9. 测试要求

至少补充以下测试：

- 当 `register_mcp_client(...)` 抛出异常时，`reg_mcp_function_level_usage(...)` 返回的仍是原 `toolkit`，且不会抛错。
- 当 `get_callable_function(...)` 抛出异常时，仅跳过该函数，不影响其他函数。
- 当 `get_callable_function(...)` 返回非 `MCPToolFunction` 对象时，仅输出 warning 并跳过。
- 当 Agent 创建过程中 MCP 注册失败时，`create_agent()` 仍能返回 agent 实例。
- 使用 `caplog` 断言 warning 中包含关键上下文，例如 host、transport、函数名或 skipped 语义。

如果本轮只做最小实现，至少应覆盖：

- 一个“整组 MCP 注册失败但 agent 创建成功”的测试。
- 一个“单函数注册失败但不抛错”的测试。

## 10. 实施建议

推荐按以下顺序实施：

1. 在 `tests` 中先补失败用例，固定软失败语义。
2. 在 `app/agent/mcp_registry.py` 引入 `logging`，替换 `print`。
3. 对全量注册路径添加 warning 降级。
4. 对按函数名注册路径添加逐函数 warning 降级。
5. 运行目标测试并确认 `factory.py` 调用链保持稳定。

## 11. 结论

本次调整的核心不是增强 MCP 功能，而是收敛外部依赖的失败边界。

MCP 应被视为可选增强能力，而不是阻断 Agent 主流程的硬门槛。将注册阶段改为“软失败 + warning + 跳过”后，可以显著提升请求可用性，同时保留足够的排障信息。对于当前项目，这是比“严格失败”更合理的默认语义。
