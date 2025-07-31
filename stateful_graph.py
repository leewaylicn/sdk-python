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


class UserInteractionRequiredException(Exception):
    """用户交互需求异常 - 用于暂停Graph执行"""
    
    def __init__(self, interaction_request: Dict[str, Any]):
        self.interaction_request = interaction_request
        super().__init__(f"User interaction required for node: {interaction_request.get('node_id')}")


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
        
        # 用户交互状态
        self.interaction_mode = "auto"  # "auto" | "waiting_user"
        self.pending_interaction = None
        
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
    
    def _has_user_input_for_node(self, node_id: str) -> bool:
        """检查节点是否已有用户输入"""
        user_input_key = f"{node_id}_user_input"
        return user_input_key in self.state_manager.global_state
    
    def _get_node_raw_output(self, node_id: str) -> Any:
        """获取节点的原始输出"""
        return self.state_manager.global_state.get(f"{node_id}_result", {})
    
    def _request_user_input(self, from_node):
        """请求用户输入 - 发送原始Agent输出"""
        
        # 1. 获取节点的原始输出
        node_result = self._get_node_raw_output(from_node.node_id)
        
        # 2. 构建交互请求（不依赖具体字段）
        interaction_request = {
            "node_id": from_node.node_id,
            "node_name": getattr(from_node.executor, 'name', from_node.node_id),
            "raw_output": node_result,  # 完整的Agent输出
            "current_state": self.state_manager.get_state(),  # 当前完整状态
            "timestamp": time.time()
        }
        
        # 3. 设置等待状态
        self.interaction_mode = "waiting_user"
        self.pending_interaction = {
            "node_id": from_node.node_id,
            "original_output": node_result
        }
        
        # 4. 输出给终端
        self._output_to_terminal(interaction_request)
        
        # 5. 抛出异常暂停执行
        raise UserInteractionRequiredException(interaction_request)
    
    def _output_to_terminal(self, interaction_request: Dict):
        """输出交互请求到终端"""
        print(f"\n🔔 用户交互请求:")
        print(f"节点: {interaction_request['node_id']}")
        print(f"原始输出: {json.dumps(interaction_request['raw_output'], ensure_ascii=False, indent=2)}")
        
        # 如果输出中包含选项，显示选项列表
        raw_output = interaction_request['raw_output']
        if isinstance(raw_output, dict) and 'options' in raw_output:
            print(f"可选项: {raw_output['options']}")
        
        print(f"请提供用户输入...")
        
        # 在实际应用中，这里会通过API/WebSocket等方式发送给前端
        # self.frontend_api.send_interaction_request(interaction_request)
    
    def provide_user_input(self, user_input: Any):
        """接收用户输入并更新状态"""
        
        if self.interaction_mode != "waiting_user":
            raise ValueError("Graph is not waiting for user input")
        
        node_id = self.pending_interaction["node_id"]
        original_output = self.pending_interaction["original_output"]
        
        # 1. 保存用户输入到独立的状态键
        self._store_user_input(node_id, user_input, original_output)
        
        # 2. 更新状态以包含用户输入信息
        self._update_state_with_user_input(node_id, user_input)
        
        # 3. 恢复执行
        self.interaction_mode = "auto"
        self.pending_interaction = None
        
        # 4. 继续Graph执行
        return self._continue_execution()
    
    def _store_user_input(self, node_id: str, user_input: Any, original_output: Dict):
        """将用户输入存储到独立的状态键中，保持数据分离"""
        
        user_input_data = {
            "input": user_input,
            "timestamp": time.time(),
            "node_id": node_id,
            "original_output": original_output
        }
        
        # 使用清晰的命名存储用户输入
        user_input_key = f"{node_id}_user_input"
        self.state_manager.global_state[user_input_key] = user_input_data
        
        # 记录用户交互
        self.state_manager._log_change(node_id, "user_input_received", {
            "user_input": user_input,
            "stored_at": user_input_key
        })
    
    def _update_state_with_user_input(self, node_id: str, user_input: Any):
        """基于用户输入更新业务状态字段"""
        
        # 获取原始输出
        original_output = self.state_manager.global_state.get(f"{node_id}_result", {})
        
        # 创建包含用户输入的增强状态
        enhanced_state = original_output.copy() if isinstance(original_output, dict) else {}
        
        # 根据用户输入类型更新相关状态字段
        if isinstance(user_input, dict):
            # 如果用户输入是结构化数据，直接合并
            enhanced_state.update(user_input)
        else:
            # 如果是简单输入，添加到特定字段
            enhanced_state["user_selection"] = user_input
        
        # 标记包含用户交互
        enhanced_state["has_user_interaction"] = True
        enhanced_state["user_input_timestamp"] = time.time()
        
        # 重新提取状态（基于增强后的数据）
        self.state_manager.extract_state_from_agent_output(node_id, json.dumps(enhanced_state))
        
        # 额外处理：直接更新全局状态中的用户输入字段
        if isinstance(user_input, dict):
            for key, value in user_input.items():
                self.state_manager.global_state[key] = value
        else:
            self.state_manager.global_state["user_selection"] = user_input
        
        # 标记用户交互
        self.state_manager.global_state["has_user_interaction"] = True
        self.state_manager.global_state["user_input_timestamp"] = enhanced_state["user_input_timestamp"]
        
        # 记录状态更新
        self.state_manager._log_change(node_id, "state_updated_with_user_input", {
            "enhanced_state": enhanced_state,
            "direct_updates": user_input if isinstance(user_input, dict) else {"user_selection": user_input}
        })
    
    def _continue_execution(self):
        """继续Graph执行 - 真实实现"""
        try:
            # 1. 重新检查所有节点的就绪状态
            # 由于用户输入已经合并到状态中，之前被阻塞的边现在可能可以执行了
            
            # 2. 找到所有可以执行的节点
            ready_nodes = []
            for node_id, node in self.nodes.items():
                if node.execution_status == Status.PENDING:
                    # 检查节点的所有依赖是否满足
                    if self._is_node_ready_to_execute(node):
                        ready_nodes.append(node)
            
            # 3. 如果有就绪的节点，创建一个新的执行任务
            if ready_nodes:
                print(f"🔄 继续执行，发现 {len(ready_nodes)} 个就绪节点")
                
                # 由于Graph的异步执行机制复杂，这里采用简化的方式
                # 实际应用中，前端应该重新调用graph()来完整执行
                return {
                    "status": "ready_to_continue",
                    "ready_nodes": [node.node_id for node in ready_nodes],
                    "interaction_mode": self.interaction_mode,
                    "message": f"用户输入已处理，发现 {len(ready_nodes)} 个就绪节点，请重新调用graph()继续执行"
                }
            else:
                # 没有更多可执行的节点，执行完成
                return {
                    "status": "execution_completed",
                    "interaction_mode": self.interaction_mode,
                    "message": "用户输入已处理，Graph执行完成"
                }
                
        except Exception as e:
            print(f"❌ 继续执行失败: {str(e)}")
            return {
                "status": "continue_execution_failed",
                "error": str(e),
                "interaction_mode": self.interaction_mode,
                "message": "继续执行时发生错误"
            }
    
    def _is_node_ready_to_execute(self, node: GraphNode) -> bool:
        """检查节点是否准备好执行"""
        try:
            # 检查节点的所有依赖边是否满足条件
            for edge in self.edges:
                if edge.to_node == node:
                    # 检查源节点是否已完成
                    if edge.from_node.execution_status != Status.COMPLETED:
                        continue
                    
                    # 检查边的条件是否满足
                    if edge.condition and not edge.condition(self.state):
                        continue
                    
                    # 如果有任何一条边满足条件，节点就可以执行
                    return True
            
            # 如果是入口节点（没有依赖），也可以执行
            return node in self.entry_points
            
        except Exception as e:
            print(f"⚠️ 检查节点就绪状态失败 ({node.node_id}): {str(e)}")
            return False


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
        
        # 将graph实例保存到state_manager的内部属性中（不会被序列化）
        self.state_manager._graph_instance = stateful_graph
        
        return stateful_graph
    
    def add_state_aware_edge(self, from_node, to_node, 
                           condition_func: Callable[[StateManager], bool],
                           requires_user_input: bool = False):
        """添加基于状态的条件边 - 支持用户交互的通用实现
        
        ✅ 优势：由于继承模式的实时状态处理，条件函数可以访问最新的状态
        
        Args:
            from_node: 源节点
            to_node: 目标节点
            condition_func: 条件函数，接收StateManager作为参数，可以访问最新状态（包括用户输入）
            requires_user_input: 是否需要用户输入才能执行这条边
        """
        def enhanced_state_aware_condition(graph_state: GraphState) -> bool:
            """支持用户交互的增强条件函数"""
            try:
                # 1. 检查是否需要用户输入
                if requires_user_input:
                    # 从state_manager的内部属性获取graph实例
                    graph_instance = getattr(self.state_manager, '_graph_instance', None)
                    
                    if graph_instance and not graph_instance._has_user_input_for_node(from_node.node_id):
                        # 需要用户输入但还没有输入 - 请求用户输入
                        graph_instance._request_user_input(from_node)
                        return False  # 暂停执行这条边
                
                # 2. 执行正常的条件检查（现在可以访问用户输入）
                result = condition_func(self.state_manager)
                print(f"   🔍 状态感知条件检查: {from_node.node_id} -> {to_node.node_id} = {result}")
                
                # 显示当前状态信息
                current_state = self.state_manager.get_state()
                key_states = {k: v for k, v in current_state.items() 
                             if not k.endswith('_result') and not k.startswith('_')}
                if key_states:
                    print(f"       当前状态: {json.dumps(key_states, ensure_ascii=False)}")
                
                return result
                
            except UserInteractionRequiredException:
                # 用户交互异常，重新抛出
                raise
            except Exception as e:
                print(f"   ⚠️  状态感知条件检查失败: {str(e)}")
                return False
        
        return self.add_edge(from_node, to_node, enhanced_state_aware_condition)
    
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