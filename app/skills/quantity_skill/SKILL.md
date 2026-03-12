---
name: order_complete_quantity_query
description: 用于查询用户当前订单的完工数量
---

# 订单完工数量查询技能

## 技能描述
本技能用于查询当前用户的订单完工数量。通过获取当前时间 → 获取当前用户信息 → 查询用户订单号 → 查询订单完工数量的流程，返回订单的完工数量。

## 适用场景
- 用户想要查询当前订单的完工进度
- 用户想要了解某个订单的生产完成情况

## 工具列表

### 1. get_current_date_time
获取当前登录用户的系统时间。

**输入参数：**
- `_t`: 固定值 "1"

**输出：**
- 当前系统时间

---

### 2. get_current_user_info
获取当前登录用户的信息。

**输入参数：**
- `_t`: 固定值 "1"

**输出：**
- 用户名（张三、李四等）

---

### 3. get_order_no_by_user_name
根据用户名查询对应的订单号。

**输入参数：**
- `_t`: 固定值 "1"
- `username`: 用户名（从get_current_user_info获取）

**输出：**
- 订单号（如：SFC20230401-0001）

---

### 4. get_order_complete_quantity_by_order_no
根据订单号查询完工数量。

**输入参数：**
- `_t`: 固定值 "1"
- `orderNo`: 订单号（从get_order_no_by_user_name获取）

**输出：**
- 完工数量（如：34512.87590）

---

## 使用流程

1. **获取当前时间**
   调用 `get_current_date_time` 工具，获取当前系统时间

2. **获取当前用户信息**
   调用 `get_current_user_info` 工具

3. **根据用户名获取订单号**
   调用 `get_order_no_by_user_name` 工具，传入步骤1获取的用户名

4. **查询订单完工数量**
   调用 `get_order_complete_quantity_by_order_no` 工具，传入步骤2获取的订单号

5. **返回结果**
   将查询到的完工数量返回给用户

---

## 示例对话

**用户：** 查询我的订单完工数量

**助手：** 好的，我来帮您查询当前订单的完工数量。

**助手（工具调用）：** 
```json
{
    "type": "tool_use",
    "name": "get_current_user_info",
    "input": {"_t": "1"}
}
```

**系统：** 
```json
{
    "type": "tool_result",
    "name": "get_current_user_info",
    "output": [{"type": "text", "text": "当前用户：张三"}]
}
```

**助手（工具调用）：** 
```json
{
    "type": "tool_use",
    "name": "get_order_no_by_user_name",
    "input": {"_t": "1", "username": "张三"}
}
```

**系统：** 
```json
{
    "type": "tool_result",
    "name": "get_order_no_by_user_name",
    "output": [{"type": "text", "text": "SFC20230401-0001"}]
}
```

**助手（工具调用）：** 
```json
{
    "type": "tool_use",
    "name": "get_order_complete_quantity_by_order_no",
    "input": {"_t": "1", "orderNo": "SFC20230401-0001"}
}
```

**系统：** 
```json
{
    "type": "tool_result",
    "name": "get_order_complete_quantity_by_order_no",
    "output": [{"type": "text", "text": "34512.87590"}]
}
```

**助手：** 您的当前订单（SFC20230401-0001）的完工数量是 **34512.87590**。

---

## 注意事项

1. 本技能假设每个用户只有一个当前订单
2. 完工数量的单位需要根据实际业务场景确定
3. 如果查询不到用户或订单，应返回相应的错误提示




