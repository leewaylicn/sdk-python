#!/usr/bin/env python3
"""
StatefulGraph设计方案 - 基于Graph实现优雅的状态管理

核心思路：
1. 继承Graph，重写关键的执行方法
2. 在节点执行前后插入状态处理逻辑
3. 为edge condition提供状态访问能力
4. 使用Agent.state作为状态存储

优势：
- 实时状态处理：在节点执行时立即处理状态
- 真正的状态感知条件边：条件函数可以访问最新的状态
- 更强的状态同步能力：状态注入和提取在执行时进行
"""

import asyncio
import json
import time
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime

from strands import Agent
from strands.multiagent.graph import Graph, GraphBuilder, GraphNode, GraphState, GraphResult
from strands.multiagent.base import NodeResult, Status
from strands.types.content import ContentBlock


#===================================
#        Very Important： State Machine（Prompt中需要返回对应的状态字段，以便graph变迁）
#===================================

class UnifiedAgentState:
    """统一的Agent状态字段定义 - 所有Agent使用相同的状态字段
    
    设计原则（基于multi_agent_customer_service_simplified.py）：
    1. 极简设计 - 只定义核心的状态字段映射
    2. 业务导向 - 字段直接对应业务需求  
    3. 配置驱动 - 通过UNIFIED_STATE_MAPPING配置状态同步
    4. 易于理解 - 清晰的注释说明每个字段的作用
    """
    
    # 统一的状态字段映射 - JSON字段名 -> agent.state字段名
    # 注意：只包含需要在Agent间传递的核心状态字段
    # analysis, entities, response 等字段可以在JSON输出中返回，但不需要同步到state
    UNIFIED_STATE_MAPPING = {
        # 业务核心字段 - 需要在Agent间传递
        "subject_type": "subject_type",           # booking, activity, other
        "activity_id": "activity_id",             # abcxxxxx (用户提供或查询得到)
        "booking_id": "booking_id",               # defxxxx (用户提供或查询得到)  
        "recent_bookings": "recent_bookings",     # [order no:xxx] (客户端填充)
        "contact_reason": "contact_reason",       # 通过detect_contact_reason工具映射到可选卡片
        "event_type": "event_type",               # click, chat
        "intent_type": "intent_type",             # 意图类型
        "priority": "priority",                   # 优先级
        
        # 状态机关键字段 - 影响Graph路由
        "stage": "stage",                         # 当前执行的Agent名称
        "status": "status",                       # 当前执行状态 (Success, Failed, Processing)
        "requires_human": "requires_human",       # 是否需要人工干预
        "confidence": "confidence",               # 置信度 0.0-1.0
    }


class StateManager:
    """状态管理器 - 基于UnifiedAgentState的状态机模式"""
    
    def __init__(self):
        self.agents: Dict[str, Agent] = {}
        self.global_state: Dict[str, Any] = {}
        self.state_history: List[Dict[str, Any]] = []
    
    def register_agent(self, agent_id: str, agent: Agent):
        """注册Agent"""
        self.agents[agent_id] = agent
        print(f"   📋 已注册Agent: {agent_id}")
    
    def inject_state_to_agent(self, agent_id: str):
        """将全局状态注入到Agent.state"""
        if agent_id not in self.agents:
            return
        
        agent = self.agents[agent_id]
        
        # 注入全局状态到Agent.state
        for key, value in self.global_state.items():
            if not key.endswith('_result'):  # 跳过结果字段
                agent.state.set(key, value)
        
        if self.global_state:
            self._log_change(agent_id, "inject", self.global_state)
    
    def extract_state_from_agent_output(self, agent_id: str, output_text: str) -> bool:
        """从Agent输出中提取状态，返回是否成功"""
        if agent_id not in self.agents:
            return False
        
        try:
            # 解析JSON
            import re
            json_match = re.search(r'\{.*\}', output_text, re.DOTALL)
            if json_match:
                parsed_data = json.loads(json_match.group())
                
                # 使用StateManager内部的状态验证和标准化
                validated_data = self._validate_and_normalize_state(agent_id, parsed_data)
                
                agent = self.agents[agent_id]
                
                # 更新Agent.state - 使用UnifiedAgentState的映射
                updated_fields = {}
                for json_field, state_field in UnifiedAgentState.UNIFIED_STATE_MAPPING.items():
                    if json_field in validated_data:
                        value = validated_data[json_field]
                        agent.state.set(state_field, value)
                        updated_fields[state_field] = value
                        # 同时更新全局状态
                        self.global_state[state_field] = value
                
                # 保存完整结果
                agent.state.set(f"{agent_id}_result", validated_data)
                self.global_state[f"{agent_id}_result"] = validated_data
                
                if updated_fields:
                    self._log_change(agent_id, "extract", updated_fields)
                    return True
                    
        except Exception as e:
            print(f"   ⚠️  状态提取失败 ({agent_id}): {str(e)}")
            return False
        
        return False
    
    def _validate_and_normalize_state(self, agent_id: str, state_data: Dict[str, Any]) -> Dict[str, Any]:
        """验证和标准化状态数据 - 极简实现，只确保基本字段
        
        注意：如果你需要复杂的状态验证逻辑，建议使用标准的Graph而不是StatefulGraph
        """
        if not isinstance(state_data, dict):
            return {"stage": agent_id, "status": "Success"}
        
        validated_data = state_data.copy()
        
        # 只确保最基本的必需字段存在
        validated_data.setdefault('stage', agent_id)
        validated_data.setdefault('status', 'Success')
        
        return validated_data
    
    def get_state(self, key: str = None) -> Any:
        """获取状态"""
        if key is None:
            return self.global_state.copy()
        return self.global_state.get(key)
    
    def _log_change(self, agent_id: str, operation: str, changes: Dict[str, Any]):
        """记录状态变化"""
        change_record = {
            "timestamp": datetime.now().isoformat(),
            "agent_id": agent_id,
            "operation": operation,
            "changes": changes
        }
        self.state_history.append(change_record)
        
        print(f"\n📝 [{change_record['timestamp']}] {agent_id} - {operation}")
        print(f"   🔄 状态变化: {json.dumps(changes, ensure_ascii=False, indent=2)}")


class StatefulGraph(Graph):
    """支持状态管理的Graph实现 - 继承模式，实时状态处理"""
    
    def __init__(self, nodes: dict[str, GraphNode], edges: set, entry_points: set, state_manager: StateManager = None):
        super().__init__(nodes, edges, entry_points)
        self.state_manager = state_manager or StateManager()
        
        # 注册所有Agent到状态管理器
        for node_id, node in nodes.items():
            if hasattr(node.executor, 'state'):  # 确保是Agent
                self.state_manager.register_agent(node_id, node.executor)
    
    async def _execute_node(self, node: GraphNode) -> None:
        """重写节点执行方法，添加状态处理逻辑"""
        node.execution_status = Status.EXECUTING
        print(f"\n🔄 执行节点: {node.node_id}")
        
        # 1. 执行前：注入状态
        self.state_manager.inject_state_to_agent(node.node_id)
        
        start_time = time.time()
        try:
            # 2. 执行节点（调用父类逻辑）
            await super()._execute_node(node)
            
            # 3. 执行后：提取状态
            if node.result and node.result.result:
                output_text = self._extract_output_text(node.result)
                success = self.state_manager.extract_state_from_agent_output(node.node_id, output_text)
                
                if success:
                    print(f"   ✅ {node.node_id} 状态提取成功")
                else:
                    print(f"   ⚠️  {node.node_id} 状态提取失败，使用fallback")
                    self._apply_fallback_state(node.node_id)
            
        except Exception as e:
            print(f"   ❌ {node.node_id} 执行失败: {str(e)}")
            # 应用错误fallback
            self._apply_error_fallback(node.node_id, str(e))
            raise
    
    def _extract_output_text(self, node_result: NodeResult) -> str:
        """从NodeResult中提取输出文本"""
        try:
            result = node_result.result
            
            # 处理AgentResult
            if hasattr(result, 'message') and result.message:
                if isinstance(result.message, dict):
                    content_blocks = result.message.get('content', [])
                    if content_blocks and isinstance(content_blocks[0], dict):
                        return content_blocks[0].get('text', str(result))
                elif hasattr(result.message, 'content'):
                    content = result.message.content
                    if content and isinstance(content, list) and len(content) > 0:
                        if isinstance(content[0], dict) and 'text' in content[0]:
                            return content[0]['text']
            
            return str(result)
        except Exception:
            return str(node_result.result)
    
    def _apply_fallback_state(self, agent_id: str):
        """应用fallback状态"""
        fallback_state = {
            "stage": agent_id,
            "status": "Success", 
            "confidence": 0.5,
            "fallback": True
        }
        
        # 更新到Agent.state和全局状态
        if agent_id in self.state_manager.agents:
            agent = self.state_manager.agents[agent_id]
            for key, value in fallback_state.items():
                agent.state.set(key, value)
                self.state_manager.global_state[key] = value
        
        self.state_manager._log_change(agent_id, "fallback", fallback_state)
    
    def _apply_error_fallback(self, agent_id: str, error_msg: str):
        """应用错误fallback状态"""
        error_state = {
            "stage": agent_id,
            "status": "Failed",
            "confidence": 0.0,
            "error": True,
            "error_message": error_msg
        }
        
        if agent_id in self.state_manager.agents:
            agent = self.state_manager.agents[agent_id]
            for key, value in error_state.items():
                agent.state.set(key, value)
                self.state_manager.global_state[key] = value
        
        self.state_manager._log_change(agent_id, "error_fallback", error_state)


class StatefulGraphBuilder(GraphBuilder):
    """支持状态管理的GraphBuilder - 继承模式版本"""
    
    def __init__(self):
        super().__init__()
        # 使用UnifiedAgentState的状态机模式
        self.state_manager = StateManager()
    
    def build(self) -> StatefulGraph:
        """构建StatefulGraph"""
        if not self.nodes:
            raise ValueError("Graph must contain at least one node")
        
        # Auto-detect entry points if none specified
        if not self.entry_points:
            self.entry_points = {node for node_id, node in self.nodes.items() if not node.dependencies}
            if not self.entry_points:
                raise ValueError("No entry points found - all nodes have dependencies")
        
        # Validate graph structure
        self._validate_graph()
        
        # 创建StatefulGraph并传入state_manager
        stateful_graph = StatefulGraph(
            nodes=self.nodes.copy(), 
            edges=self.edges.copy(), 
            entry_points=self.entry_points.copy(),
            state_manager=self.state_manager
        )
        
        return stateful_graph
    
    def add_state_aware_edge(self, from_node, to_node, condition_func: Callable[[StateManager], bool]):
        """添加基于状态的条件边 - 真正的状态感知实现
        
        ✅ 优势：由于继承模式的实时状态处理，条件函数可以访问最新的状态
        
        Args:
            from_node: 源节点
            to_node: 目标节点
            condition_func: 条件函数，接收StateManager作为参数，可以访问最新状态
        """
        def state_aware_condition(graph_state: GraphState) -> bool:
            """包装条件函数，注入state_manager访问能力"""
            try:
                # 通过闭包捕获state_manager引用，提供真正的状态访问
                result = condition_func(self.state_manager)
                print(f"   🔍 状态感知条件检查: {from_node.node_id} -> {to_node.node_id} = {result}")
                
                # 显示当前状态信息
                current_state = self.state_manager.get_state()
                key_states = {k: v for k, v in current_state.items() if not k.endswith('_result')}
                if key_states:
                    print(f"       当前状态: {json.dumps(key_states, ensure_ascii=False)}")
                
                return result
            except Exception as e:
                print(f"   ⚠️  状态感知条件检查失败: {str(e)}")
                return False
        
        return self.add_edge(from_node, to_node, state_aware_condition)
    
    def add_node_with_state(self, executor: Agent, node_id: str = None) -> 'GraphNode':
        """添加节点并自动注册到状态管理器"""
        node = self.add_node(executor, node_id)
        
        # 立即注册到状态管理器
        if hasattr(executor, 'state'):
            self.state_manager.register_agent(node.node_id, executor)
        
        return node


# ==================== 使用示例 ====================

def create_stateful_customer_service():
    """创建支持状态管理的客户服务系统 - 继承模式版本"""
    
    # 创建StatefulGraphBuilder - 使用UnifiedAgentState的状态机模式
    builder = StatefulGraphBuilder()
    
    # 创建Agent
    entry_agent = Agent(
        name="entry_agent",
        system_prompt="""分析用户输入类型，返回JSON格式：
{
  "event_type": "click/chat",
  "confidence": 0.8,
  "stage": "entry_agent",
  "status": "Success"
}"""
    )
    
    route_agent = Agent(
        name="route_agent",
        system_prompt="""判断是否需要人工干预，返回JSON格式：
{
  "subject_type": "booking/activity/other",
  "requires_human": true/false,
  "confidence": 0.9,
  "stage": "route_agent", 
  "status": "Success"
}"""
    )
    
    intent_agent = Agent(name="intent_agent", system_prompt="意图分析Agent")
    transfer_agent = Agent(name="transfer_agent", system_prompt="人工转接Agent")
    answer_agent = Agent(name="answer_agent", system_prompt="最终回答Agent")
    
    # 添加节点
    entry_node = builder.add_node(entry_agent, "entry_agent")
    route_node = builder.add_node(route_agent, "route_agent")
    intent_node = builder.add_node(intent_agent, "intent_agent")
    transfer_node = builder.add_node(transfer_agent, "transfer_agent")
    answer_node = builder.add_node(answer_agent, "answer_agent")
    
    # 添加边
    builder.add_edge(entry_node, route_node)
    
    # 基于状态的条件路由 - 真正的状态感知
    def needs_human(state_manager: StateManager) -> bool:
        """检查是否需要人工干预 - 可以访问最新状态"""
        requires_human = state_manager.get_state("requires_human")
        stage = state_manager.get_state("stage")
        status = state_manager.get_state("status")
        
        print(f"     🤔 人工干预检查: requires_human={requires_human}, stage={stage}, status={status}")
        
        return (stage == "route_agent" and 
                status == "Success" and 
                requires_human == True)
    
    def needs_auto_processing(state_manager: StateManager) -> bool:
        """检查是否需要自动处理 - 可以访问最新状态"""
        requires_human = state_manager.get_state("requires_human")
        stage = state_manager.get_state("stage")
        status = state_manager.get_state("status")
        
        print(f"     🤖 自动处理检查: requires_human={requires_human}, stage={stage}, status={status}")
        
        return (stage == "route_agent" and 
                status == "Success" and 
                not requires_human)
    
    # 使用真正的状态感知条件边
    builder.add_state_aware_edge(route_node, transfer_node, needs_human)
    builder.add_state_aware_edge(route_node, intent_node, needs_auto_processing)
    builder.add_edge(intent_node, answer_node)
    
    # 设置入口点
    builder.set_entry_point("entry_agent")
    
    return builder.build()


if __name__ == "__main__":
    print("🎯 StatefulGraph设计方案测试 - 继承模式，实时状态处理")
    
    # 创建系统
    graph = create_stateful_customer_service()
    
    # 测试用例
    test_input = "我要申请退款，订单号12345"
    
    print(f"\n🧪 测试输入: {test_input}")
    print("="*60)
    
    try:
        result = graph(test_input)
        
        print(f"\n✅ 执行完成:")
        print(f"  状态: {result.status}")
        print(f"  完成节点: {result.completed_nodes}/{result.total_nodes}")
        print(f"  执行时间: {result.execution_time}ms")
        
        # 打印最终状态
        final_state = graph.state_manager.get_state()
        print(f"\n📊 最终状态:")
        print(json.dumps(final_state, ensure_ascii=False, indent=2))
        
    except Exception as e:
        print(f"❌ 执行失败: {str(e)}")
        import traceback
        traceback.print_exc()