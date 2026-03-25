# LiteLLM 透传参数中间件设计

## 1. 背景

当前项目通过 LiteLLM 网关访问大模型。LiteLLM 会对其本地判定为“不支持”的 OpenAI 风格参数直接报错，而不是默认透传。虽然可以通过 `allowed_openai_params` 放行，但现有实现把这部分能力绑定在模型级配置中，导致每接入一个新模型时，都可能需要补充一轮配置并重新发布中间件。

这对当前项目的定位不合适。该项目是一个无状态 AI 引擎中间件，兼容性和扩展性优先，特别是在主要对接国内模型、且模型参数迭代较快的情况下，不应要求每次引入新模型时都同步维护重复的透传名单。

## 2. 当前问题

当前实现的主要问题如下：

- `app/agent/factory.py` 中会主动发送 `parallel_tool_calls=True`。
- `config/model_request.toml` 中又要求为每个模型重复声明 `allowed_openai_params = ["parallel_tool_calls"]`。
- `app/config.py` 目前只把模型级 `allowed_openai_params` 合并进 `extra_body`，配置层和发包层职责耦合。
- 外部会话请求目前没有请求级透传参数入口，无法在不改配置的情况下临时透传新参数。

这会带来两个直接后果：

- 模型接入成本偏高，新增模型时经常要重复补配置。
- LiteLLM 本地支持矩阵滞后时，中间件自身会成为兼容性瓶颈。

## 3. 设计目标

本次设计目标如下：

- 对外提供单一的请求级透传参数入口。
- 请求级透传参数可以携带值，并且必须真正发往 LiteLLM。
- 请求级参数优先级高于默认配置，但不能覆盖中间件保留字段。
- 让 `allowed_openai_params` 从“按模型维护的完整名单”变成“引擎自动生成的放行名单”。
- 减少接入新模型时对配置文件的重复修改需求。
- 保持对国内模型常用参数的高兼容性。
- 保留模型级例外修正能力。

## 4. 非目标

本设计不解决以下问题：

- 不负责判断下游模型服务商是否真实支持某个参数。
- 不引入 LiteLLM 运行时能力探测。
- 不通过 `drop_params=True` 静默删除不支持参数作为主流程。
- 不改变现有无状态会话编排逻辑。

## 5. 关键设计原则

### 5.1 中间件语义与 LiteLLM 语义分离

对外 API 的 `allowed_openai_params` 不再直接等同于 LiteLLM 原生的字符串数组语义。

对外语义：

- `allowed_openai_params` 是一个“带值的透传参数对象”。
- 它既表达参数名，也表达参数值。
- 它表示“这些参数本轮必须透传给 LiteLLM”。

对内语义：

- 中间件将该对象拆成两部分：
  - 实际参数值，直接并入 LiteLLM 请求参数。
  - 参数名数组，写入 `extra_body.allowed_openai_params`。

### 5.2 请求级优先

请求级透传参数优先级高于引擎默认参数和模型默认参数，但不得覆盖保留字段。

### 5.3 配置层只做默认和例外

配置文件只负责：

- 全局兼容放行名单。
- 默认模型参数。
- 模型级例外修正。
- 供应商私有 `extra_body`。

配置文件不再承担“为每个模型重复声明引擎已知透传参数”的职责。

## 6. 外部请求契约

会话请求中新增字段：

```json
{
  "allowed_openai_params": {
    "reasoning_effort": "high",
    "parallel_tool_calls": false,
    "frequency_penalty": 0.3
  }
}
```

字段语义如下：

- key 表示本轮要透传的参数名。
- value 表示本轮要发送的参数值。
- 这些 key/value 会真正发往 LiteLLM。
- 这些 key 会自动加入 LiteLLM 需要的 `allowed_openai_params` 名单。
- 该字段只做补充和覆盖，不负责移除既有参数。

## 7. 配置文件结构

`config/model_request.toml` 调整为以下结构：

```toml
[global]
compat_allowed_openai_params = [
  "parallel_tool_calls",
  "tool_choice",
  "reasoning_effort",
  "frequency_penalty",
  "presence_penalty",
  "top_p",
  "top_k",
  "min_p",
  "response_format",
]
non_overridable_request_params = [
  "model",
  "messages",
  "stream",
  "api_key",
  "base_url",
]

[default]
model_params = {}
extra_allowed_openai_params = []
blocked_allowed_openai_params = []
extra_body = {}

[models."doubao-seed-2-0-mini-260215"]
model_params = {}
extra_allowed_openai_params = []
blocked_allowed_openai_params = []
extra_body = {}
```

各字段职责如下：

- `global.compat_allowed_openai_params`
  - 全局兼容放行名单。
  - 用于覆盖两类场景：
    - 当前引擎已经会主动发出的参数。
    - 预期国内模型常用、LiteLLM 可能滞后拦截的参数。

- `global.non_overridable_request_params`
  - 请求级禁止覆盖的保留字段名单。

- `default.model_params`
  - 默认模型参数值。
  - 会直接作为 LiteLLM 请求参数发送。

- `default.extra_allowed_openai_params`
  - 额外补充的默认放行名单。

- `default.blocked_allowed_openai_params`
  - 默认屏蔽名单。

- `default.extra_body`
  - 供应商私有 `extra_body` 字段。

- `models."<name>"` 下的同名字段
  - 用于模型级修正，而不是完整重复声明。

## 8. 内部数据分层

内部需要区分三类数据：

### 8.1 带值参数

- 引擎默认参数
- `default.model_params`
- `models."<name>".model_params`
- 请求级 `allowed_openai_params` 对象

这些参数最终会真正发给 LiteLLM。

### 8.2 仅名单参数

- `global.compat_allowed_openai_params`
- `default.extra_allowed_openai_params`
- `models."<name>".extra_allowed_openai_params`
- `default.blocked_allowed_openai_params`
- `models."<name>".blocked_allowed_openai_params`

这些参数只参与名单生成，不直接携带值。

### 8.3 供应商私有体字段

- `default.extra_body`
- `models."<name>".extra_body`

这些字段只进入 `extra_body`，不参与请求级透传优先级竞争。

## 9. 合并规则

### 9.1 参数值合并顺序

最终发送给 LiteLLM 的实际参数值按如下顺序合并：

1. 引擎默认参数
2. `default.model_params`
3. `models."<name>".model_params`
4. 请求级 `allowed_openai_params`

其中：

- 后者覆盖前者。
- 请求级优先。
- 如果请求级参数命中 `global.non_overridable_request_params`，直接返回 4xx。

### 9.2 放行名单生成规则

最终 `effective_allowed_openai_params` 按如下规则生成：

```text
effective_allowed_openai_params =
  global.compat_allowed_openai_params
  ∪ default.extra_allowed_openai_params
  ∪ models.<name>.extra_allowed_openai_params
  ∪ keys(request.allowed_openai_params)
  ∪ keys(已知高风险引擎默认参数)
  - default.blocked_allowed_openai_params
  - models.<name>.blocked_allowed_openai_params
```

设计说明：

- 请求级对象中的所有 key 必须进入最终 allowlist。
- 引擎主动发送且已知容易被 LiteLLM 本地拦截的参数，也应自动进入 allowlist。
- 放行名单允许“偏大”，不要求只包含 LiteLLM 当前一定会拦截的参数。
- 以稳定透传优先，不做复杂的运行时支持性判断。

### 9.3 最终发包形态

假设：

- 引擎默认：`parallel_tool_calls = true`
- 默认模型参数：`tool_choice = "auto"`
- 请求级透传：

```json
{
  "allowed_openai_params": {
    "parallel_tool_calls": false,
    "reasoning_effort": "high"
  }
}
```

则最终发给 LiteLLM 的参数近似为：

```json
{
  "temperature": 0.2,
  "parallel_tool_calls": false,
  "tool_choice": "auto",
  "reasoning_effort": "high",
  "extra_body": {
    "allowed_openai_params": [
      "parallel_tool_calls",
      "tool_choice",
      "reasoning_effort"
    ]
  }
}
```

其中：

- `parallel_tool_calls` 被请求级值覆盖。
- `reasoning_effort` 来自请求级透传。
- 三者的参数名都进入最终 allowlist。

## 10. 保留字段策略

以下字段不得被请求级 `allowed_openai_params` 覆盖：

- `model`
- `messages`
- `stream`
- `api_key`
- `base_url`

设计理由：

- 这些字段属于中间件协议控制面，不应暴露给请求级动态参数透传逻辑。
- 如果允许覆盖，会打破中间件的调用边界和安全假设。

命中这些字段时，直接返回 4xx，不做静默忽略。

## 11. 错误处理策略

以下情况直接返回请求错误：

- `allowed_openai_params` 不是对象。
- `allowed_openai_params` 的 key 不是字符串。
- `allowed_openai_params` 试图覆盖保留字段。
- 配置文件中同一参数同时出现在允许名单和屏蔽名单中。
- `model_params` 或 `extra_body` 结构非法。

以下情况允许继续执行：

- 请求级参数覆盖默认参数。
- 请求级传入一个全新的动态参数名。
- LiteLLM 当前版本本地不识别该参数，但中间件已将其加入 allowlist。

以下情况不应由中间件静默处理：

- 自动删除未知参数。
- 自动重命名非法参数。
- 自动 `drop_params=True`。
- 自动吞掉冲突配置。

原则上，明确失败优于隐式降级。

## 12. 可观测性要求

为便于排查 LiteLLM 兼容问题，每次请求应记录结构化日志，但不记录完整敏感 payload。

建议至少记录：

- `session_id`
- `model_name`
- `request_allowed_openai_param_keys`
- `effective_allowed_openai_param_keys`
- `request_overridden_param_keys`
- `blocked_param_keys`
- `final_extra_body_keys`

如果 LiteLLM 返回 `UnsupportedParamsError`，日志中还应追加：

- LiteLLM 原始错误文本
- 本轮最终 allowlist
- 本轮请求级透传 key 列表

另建议额外产出“参数来源摘要”，用于快速判断最终值来自哪一层：

```text
parallel_tool_calls <- request
tool_choice <- model_default
reasoning_effort <- request
temperature <- engine_default
```

## 13. 代码职责划分

### 13.1 `app/config.py`

负责：

- 读取 `config/model_request.toml`
- 校验 `global/default/models` 结构
- 合并默认层与模型层
- 产出结构化模型请求兼容配置对象

不负责：

- 直接拼装最终 LiteLLM 发包参数

### 13.2 请求 schema 与执行入口

负责：

- 为会话请求新增 `allowed_openai_params` 字段
- 校验类型是否合法
- 拦截保留字段覆盖

不负责：

- 决定最终参数优先级
- 拼装 LiteLLM 最终请求

### 13.3 `app/agent/factory.py`

负责：

- 合并引擎默认参数、模型默认参数、请求级透传参数
- 生成最终实际请求参数
- 生成最终 `extra_body.allowed_openai_params`
- 将两者统一发送给 LiteLLM

该文件应成为唯一的 LiteLLM 请求编排入口。

## 14. 对现有实现的预期调整

当前设计实施后，预期会带来如下变化：

- `config/model_request.toml` 不再为每个模型重复声明完整 `allowed_openai_params`。
- `app/config.py` 不再只返回扁平 `model_extra_body`。
- `app/agent/factory.py` 不再依赖“代码硬编码参数 + 配置重复放行”的双维护模式。
- 会话请求支持携带带值透传参数，并由请求级优先生效。

## 15. 测试建议

建议至少覆盖以下测试场景：

- 请求未传 `allowed_openai_params` 时，默认配置路径正常工作。
- 请求传入新的透传参数时，参数值和 allowlist 都正确下发。
- 请求覆盖默认参数时，请求级值生效。
- 请求试图覆盖保留字段时，返回 4xx。
- 模型级 `blocked_allowed_openai_params` 能正确移除名单项。
- `extra_body` 与 allowlist 合并后结构正确。
- LiteLLM 兼容错误日志包含关键诊断字段。

## 16. 实施建议

建议按以下顺序实施：

1. 调整 `config/model_request.toml` schema 和 `app/config.py` 的解析结构。
2. 为会话请求 schema 增加带值的 `allowed_openai_params` 字段。
3. 改造 `app/agent/factory.py`，统一编排最终 LiteLLM 请求。
4. 增加错误处理与结构化日志。
5. 补充配置解析、请求校验、发包合并路径测试。

## 17. 结论

本设计的核心是把当前项目中的 `allowed_openai_params` 从“按模型维护的重复字符串名单”升级为“中间件对外暴露的带值透传参数入口”，再由中间件内部转换为 LiteLLM 所需的参数值与放行名单。

这样可以同时满足：

- 新模型接入时不必频繁改配置并发布。
- 对国内模型参数迭代保持高兼容性。
- 维持中间件边界清晰。
- 在 LiteLLM 支持矩阵滞后时，仍能优先保证参数透传能力。
