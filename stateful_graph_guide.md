# StatefulGraph 使用指南

本指南详细介绍了如何使用StatefulGraph框架构建具有状态管理能力的多Agent工作流。

## 🔄 核心概念：状态同步关系

### 状态字段映射 (UNIFIED_STATE_MAPPING)

StatefulGraph通过`UnifiedAgentState.UNIFIED_STATE_MAPPING`实现Agent输出JSON与全局状态的字段映射，并通过全局字段进行node的edge的跳转，也就是说这里应该定义了主要的跳转需要的主要字段和字段值带来的跳转关系，从而实现一个状态机的规范，并注意这里把Edge的触发前加入是否和用户交互的节点触发。
所以这里最佳实践是不仅要定义字段，最好说明node和状态引发的node的跳转关系（当然后期可以考虑引入图的解析，进行简化）

```python
UNIFIED_STATE_MAPPING = {
    # Agent JSON输出字段 -> 全局状态字段
    "stage": "stage",           # 当前执行阶段
    "status": "status",         # 执行状态 (Success/Failed/Pending)
    "event_type": "event_type", # 事件类型 (chat/click)
    "requires_human": "requires_human", # 是否需要人工干预
    # ... 其他业务字段
}
```

### 状态同步流程

```
Agent执行 → JSON输出 → StateManager提取 → 更新全局状态 →   edge是否human in loop要求       →  条件边判断
    ↓                                    ↓                    ↓ 
Agent.state                        global_state         人机交互检查
    ↓                                    ↓                   ↓
局部状态                            全局共享状态            用户输入处理
                                                             ↓
                                                        更新global_state

人机交互时的状态变化：
- {node_id}_result: 保存Agent原始输出
- {node_id}_user_input: 独立存储用户输入
- global_state: 合并原始输出 + 用户输入的增强状态
```

### 三层状态结构

1. **Agent输出JSON** - Agent的原始结构化输出
2. **Agent.state** - 每个Agent的局部状态存储
3. **global_state** - 全局共享状态，供条件边使用

### 条件边中的状态访问

```python
def condition_function(state_manager: StateManager) -> bool:
    # 访问全局状态字段
    stage = state_manager.get_state("stage")
    status = state_manager.get_state("status") 
    event_type = state_manager.get_state("event_type")
    
    # 访问用户输入数据
    user_input = state_manager.get_state("node_id_user_input")
    
    # 访问Agent完整输出
    agent_result = state_manager.get_state("node_id_result")
    
    return stage == "target_stage" and status == "Success"
```

### 用户交互状态管理

```python
# 用户输入独立存储
"{node_id}_user_input": {
    "input": "用户实际输入",
    "timestamp": "输入时间戳", 
    "node_id": "关联节点ID",
    "original_output": "原始Agent输出"
}

# 原始Agent输出保持不变
"{node_id}_result": {
    "stage": "agent_stage",
    "status": "Success",
    # ... Agent的完整输出
}
```

### 快速使用示例

```python
# 1. 创建StatefulGraph
builder = StatefulGraphBuilder()

# 2. 添加节点
node1 = builder.add_node(agent1, "agent1")
node2 = builder.add_node(agent2, "agent2")

# 3. 添加状态感知条件边
def condition(state_manager: StateManager) -> bool:
    return (state_manager.get_state("stage") == "agent1" and 
            state_manager.get_state("status") == "Success")

builder.add_state_aware_edge(node1, node2, condition)

# 4. 添加用户交互边
def has_user_input(state_manager: StateManager) -> bool:
    return state_manager.get_state("agent1_user_input") is not None

builder.add_state_aware_edge(
    node1, node2, has_user_input, 
    requires_user_input=True  # 标记需要用户输入
)

# 5. 构建并执行
graph = builder.build()
result = graph("用户输入")
```

---

## 📋 StatefulGraph 概述

StatefulGraph是基于Strands Graph的增强版本，专门为需要复杂状态管理的多Agent工作流设计。它通过继承Graph并重写关键执行方法，实现了实时状态处理和真正的状态感知条件边。

### 核心特性

- **实时状态处理** - 在节点执行时立即处理状态
- **状态感知条件边** - 条件函数可以访问最新的状态
- **用户交互支持** - 支持暂停执行等待用户输入
- **统一状态映射** - 通过UNIFIED_STATE_MAPPING标准化状态字段
- **状态历史记录** - 完整的状态变化追踪

## 🏗️ 架构设计

### 核心组件

1. **UnifiedAgentState** - 统一的状态字段定义
2. **StateManager** - 状态管理器，负责状态注入和提取
3. **StatefulGraph** - 继承Graph的状态感知执行器
4. **StatefulGraphBuilder** - 构建器，支持状态感知边

### 设计原则

- **极简设计** - 只定义核心的状态字段映射
- **业务导向** - 字段直接对应业务需求
- **配置驱动** - 通过UNIFIED_STATE_MAPPING配置状态同步
- **易于理解** - 清晰的注释说明每个字段的作用

## 🚀 快速开始

### 1. 创建基本的StatefulGraph

```python
from stateful_graph import StatefulGraphBuilder, Agent

# 创建构建器
builder = StatefulGraphBuilder()

# 创建Agent
agent1 = Agent(
    name="entry_agent",
    system_prompt="""分析用户输入，返回JSON格式：
{
  "stage": "entry_agent",
  "status": "Success",
  "event_type": "chat",
  "confidence": 0.8
}"""
)

# 添加节点
node1 = builder.add_node(agent1, "entry_agent")

# 构建Graph
graph = builder.build()

# 执行
result = graph("用户输入")
```

### 2. 添加状态感知条件边

```python
# 创建两个Agent
entry_agent = Agent(name="entry_agent", system_prompt="...")
route_agent = Agent(name="route_agent", system_prompt="...")

# 添加节点
entry_node = builder.add_node(entry_agent, "entry_agent")
route_node = builder.add_node(route_agent, "route_agent")

# 定义条件函数
def entry_completed(state_manager: StateManager) -> bool:
    stage = state_manager.get_state("stage")
    status = state_manager.get_state("status")
    return stage == "entry_agent" and status == "Success"

# 添加状态感知边
builder.add_state_aware_edge(entry_node, route_node, entry_completed)
```

### 3. 支持用户交互

```python
def needs_user_input(state_manager: StateManager) -> bool:
    # 检查是否需要用户选择
    return state_manager.get_state("requires_user_selection") == True

# 添加需要用户输入的边
builder.add_state_aware_edge(
    from_node, to_node, 
    needs_user_input,
    requires_user_input=True  # 标记需要用户输入
)

# 处理用户交互异常
try:
    result = graph("用户输入")
except UserInteractionRequiredException as e:
    # 获取交互请求
    interaction_request = e.interaction_request
    
    # 显示给用户并获取输入
    user_input = get_user_input(interaction_request)
    
    # 提供用户输入并继续执行
    continue_result = graph.provide_user_input(user_input)
```

## 📊 状态管理详解

### UnifiedAgentState配置

```python
class UnifiedAgentState:
    UNIFIED_STATE_MAPPING = {
        # 业务核心字段
        "subject_type": "subject_type",     # booking, activity, other
        "activity_id": "activity_id",       # 活动ID
        "booking_id": "booking_id",         # 订单ID
        "contact_reason": "contact_reason", # 联系原因
        
        # 状态机关键字段
        "stage": "stage",                   # 当前阶段
        "status": "status",                 # 执行状态
        "requires_human": "requires_human", # 需要人工干预
        "confidence": "confidence",         # 置信度
    }
```

### StateManager使用

```python
# 获取状态
current_stage = state_manager.get_state("stage")
all_state = state_manager.get_state()  # 获取所有状态

# 检查用户输入
user_input = state_manager.get_state("node_id_user_input")
if user_input:
    actual_input = user_input["input"]
    timestamp = user_input["timestamp"]

# 获取Agent完整输出
agent_result = state_manager.get_state("node_id_result")
```

## 🔧 高级功能

### 1. 自定义状态验证

```python
class CustomStateManager(StateManager):
    def _validate_and_normalize_state(self, agent_id: str, state_data: Dict[str, Any]) -> Dict[str, Any]:
        # 自定义验证逻辑
        validated_data = super()._validate_and_normalize_state(agent_id, state_data)
        
        # 添加业务特定验证
        if "confidence" in validated_data:
            confidence = validated_data["confidence"]
            if not (0.0 <= confidence <= 1.0):
                validated_data["confidence"] = 0.5
        
        return validated_data
```

### 2. 状态历史追踪

```python
# 获取状态变化历史
history = graph.state_manager.state_history

for change in history:
    print(f"时间: {change['timestamp']}")
    print(f"Agent: {change['agent_id']}")
    print(f"操作: {change['operation']}")
    print(f"变化: {change['changes']}")
```

### 3. 复杂条件边

```python
def complex_routing_condition(state_manager: StateManager) -> bool:
    # 多字段条件判断
    stage = state_manager.get_state("stage")
    status = state_manager.get_state("status")
    confidence = state_manager.get_state("confidence")
    subject_type = state_manager.get_state("subject_type")
    
    # 复杂业务逻辑
    if stage == "route_agent" and status == "Success":
        if subject_type == "booking" and confidence > 0.8:
            return True
        elif subject_type == "activity" and confidence > 0.6:
            return True
    
    return False
```

## 🎯 最佳实践

### 1. Agent设计原则

- **结构化输出** - Agent必须返回JSON格式的结构化数据
- **状态字段完整** - 包含UNIFIED_STATE_MAPPING中定义的关键字段
- **错误处理** - 提供fallback状态以处理解析失败

```python
agent = Agent(
    name="example_agent",
    system_prompt="""
处理用户请求并返回JSON格式：
{
  "stage": "example_agent",
  "status": "Success|Failed|Processing",
  "confidence": 0.0-1.0,
  "subject_type": "booking|activity|other",
  "analysis": "详细分析结果",
  "next_action": "建议的下一步操作"
}

注意：
- stage字段必须与Agent名称一致
- status字段影响Graph的路由决策
- confidence字段用于质量评估
"""
)
```

### 2. 条件函数设计

- **明确的返回值** - 条件函数必须返回明确的布尔值
- **状态检查** - 检查必要的状态字段是否存在
- **日志记录** - 添加适当的日志以便调试

```python
def well_designed_condition(state_manager: StateManager) -> bool:
    # 1. 获取必要的状态字段
    stage = state_manager.get_state("stage")
    status = state_manager.get_state("status")
    
    # 2. 检查字段是否存在
    if not stage or not status:
        print(f"⚠️ 缺少必要的状态字段: stage={stage}, status={status}")
        return False
    
    # 3. 执行条件判断
    result = stage == "target_stage" and status == "Success"
    
    # 4. 记录判断结果
    print(f"🔍 条件检查: {stage}=={target_stage} and {status}==Success -> {result}")
    
    return result
```

### 3. 错误处理策略

```python
try:
    result = graph("用户输入")
except UserInteractionRequiredException as e:
    # 处理用户交互需求
    handle_user_interaction(e.interaction_request)
except Exception as e:
    # 处理其他执行错误
    print(f"Graph执行失败: {str(e)}")
    
    # 检查状态管理器的状态
    current_state = graph.state_manager.get_state()
    print(f"当前状态: {json.dumps(current_state, ensure_ascii=False, indent=2)}")
    
    # 查看状态历史
    for change in graph.state_manager.state_history[-5:]:  # 最近5次变化
        print(f"历史: {change}")
```

## 🔍 调试和监控

### 1. 状态追踪

StatefulGraph提供了详细的状态变化日志：

```
📝 [2024-01-01T10:00:00] entry_agent - extract
   🔄 状态变化: {
     "stage": "entry_agent",
     "status": "Success",
     "event_type": "chat",
     "confidence": 0.8
   }
```

### 2. 条件边调试

```
🔍 状态感知条件检查: entry_agent -> route_agent = True
       当前状态: {
         "stage": "entry_agent",
         "status": "Success",
         "event_type": "chat"
       }
```

### 3. 用户交互监控

```
🔔 用户交互请求:
节点: route_agent
原始输出: {
  "stage": "route_agent",
  "status": "Success",
  "options": ["选项1", "选项2", "选项3"],
  "requires_user_selection": true
}
可选项: ["选项1", "选项2", "选项3"]
请提供用户输入...
```

## 📚 完整示例

### 客户服务工作流

```python
def create_customer_service_graph():
    builder = StatefulGraphBuilder()
    
    # 创建Agent
    entry_agent = Agent(
        name="entry_agent",
        system_prompt="""分析用户输入类型，返回JSON：
{
  "stage": "entry_agent",
  "status": "Success",
  "event_type": "chat|click",
  "confidence": 0.8,
  "user_intent": "问题描述"
}"""
    )
    
    route_agent = Agent(
        name="route_agent", 
        system_prompt="""判断处理方式，返回JSON：
{
  "stage": "route_agent",
  "status": "Success", 
  "subject_type": "booking|activity|other",
  "requires_human": true|false,
  "confidence": 0.9,
  "routing_reason": "路由原因"
}"""
    )
    
    # 添加节点
    entry_node = builder.add_node(entry_agent, "entry_agent")
    route_node = builder.add_node(route_agent, "route_agent")
    
    # 添加条件边
    def entry_to_route(state_manager: StateManager) -> bool:
        return (state_manager.get_state("stage") == "entry_agent" and
                state_manager.get_state("status") == "Success")
    
    builder.add_state_aware_edge(entry_node, route_node, entry_to_route)
    
    # 设置入口点
    builder.set_entry_point("entry_agent")
    
    return builder.build()

# 使用示例
if __name__ == "__main__":
    graph = create_customer_service_graph()
    
    try:
        result = graph("我要申请退款")
        print(f"执行结果: {result.status}")
        
        # 查看最终状态
        final_state = graph.state_manager.get_state()
        print(f"最终状态: {json.dumps(final_state, ensure_ascii=False, indent=2)}")
        
    except UserInteractionRequiredException as e:
        print(f"需要用户交互: {e.interaction_request}")
```

## 🤝 与标准Graph的对比

| 特性 | 标准Graph | StatefulGraph |
|------|-----------|---------------|
| 状态管理 | 基本的GraphState | 实时状态处理 |
| 条件边 | 静态条件函数 | 状态感知条件函数 |
| 用户交互 | 不支持 | 原生支持 |
| 状态追踪 | 无 | 完整的历史记录 |
| 复杂度 | 简单 | 中等 |
| 适用场景 | 简单工作流 | 复杂业务流程 |

## 📖 总结

StatefulGraph为复杂的多Agent工作流提供了强大的状态管理能力。通过统一的状态映射、实时状态处理和状态感知条件边，它能够构建出真正智能的业务流程。

关键优势：
- **实时状态同步** - 状态变化立即反映到条件判断中
- **用户交互支持** - 原生支持暂停执行等待用户输入
- **完整的状态追踪** - 详细的状态变化历史记录
- **灵活的条件路由** - 基于最新状态的智能路由决策

适用于需要复杂状态管理的场景，如客户服务、订单处理、审批流程等业务工作流。