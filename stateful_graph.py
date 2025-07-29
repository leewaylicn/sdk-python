#!/usr/bin/env python3
"""
StatefulGraph - 通用的状态管理Graph实现

核心组件：
1. UnifiedAgentState - 极简的状态字段映射定义
2. StateManager - 状态管理器，负责状态验证、提取、注入
3. StatefulGraph - 支持状态管理的Graph实现
4. StatefulGraphBuilder - 支持状态管理的GraphBuilder

设计原则：
- 极简设计：只确保基本的stage和status字段
- 职责分离：StateManager负责状态处理，Graph负责执行
- 后处理模式：Graph执行完成后提取状态
- 易于扩展：通过UNIFIED_STATE_MAPPING配置状态字段
"""

import json
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable

# Strands imports
from strands import Agent
from strands.multiagent.graph import GraphBuilder, GraphNode, GraphState, GraphResult
from strands.multiagent.base import NodeResult, Status
from strands.types.content import ContentBlock


class UnifiedAgentState:
    """统一的Agent状态字段定义 - 极简设计，只有状态字段映射
    
    设计原则：
    1. 极简设计 - 只定义核心的状态字段映射
    2. 业务导向 - 字段直接对应业务需求  
    3. 配置驱动 - 通过UNIFIED_STATE_MAPPING配置状态同步
    4. 易于理解 - 清晰的注释说明每个字段的作用
    
    注意：如果你需要复杂的状态验证逻辑，建议使用标准的Graph而不是StatefulGraph
    """
    
    # 统一的状态字段映射 - JSON字段名 -> agent.state字段名
    # 注意：只包含需要在Agent间传递的核心状态字段
    UNIFIED_STATE_MAPPING = {
        # 状态机关键字段 - 影响Graph路由（必需）
        "stage": "stage",                         # 当前执行的Agent名称
        "status": "status",                       # 当前执行状态 (Success, Failed, Processing)
        
        # 业务字段 - 根据具体业务需求配置（可选）
        "subject_type": "subject_type",           # 主题类型
        "requires_human": "requires_human",       # 是否需要人工干预
        "confidence": "confidence",               # 置信度 0.0-1.0
        "event_type": "event_type",               # 事件类型
        "intent_type": "intent_type",             # 意图类型
        "priority": "priority",                   # 优先级
        
        # 实体字段 - 业务实体信息（可选）
        "booking_id": "booking_id",               # 订单ID
        "activity_id": "activity_id",             # 活动ID
        "contact_reason": "contact_reason",       # 联系原因
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


class StatefulGraph:
    """支持状态管理的Graph实现"""
    
    def __init__(self, nodes: dict[str, GraphNode], edges: set, entry_points: set):
        from strands.multiagent.graph import Graph
        self.graph = Graph(nodes, edges, entry_points)
        self.state_manager = StateManager()
        
        # 注册所有Agent到状态管理器
        for node_id, node in nodes.items():
            if hasattr(node.executor, 'state'):  # 确保是Agent
                self.state_manager.register_agent(node_id, node.executor)
    
    def __call__(self, task: str | list[ContentBlock], **kwargs: Any) -> GraphResult:
        """同步调用Graph并处理状态"""
        print(f"\n🚀 StatefulGraph开始执行")
        print(f"📥 任务: {task}")
        
        # 执行Graph
        result = self.graph(task, **kwargs)
        
        # 后处理：从结果中提取状态
        self._process_execution_result(result)
        
        return result
    
    def _process_execution_result(self, result: GraphResult):
        """处理执行结果，提取状态"""
        print(f"\n🔧 后处理：从执行结果中提取状态")
        
        # 按执行顺序处理每个节点的结果
        for node in result.execution_order:
            node_id = node.node_id
            node_result = result.results.get(node_id)
            
            if node_result:
                # 提取Agent输出文本
                output_text = self._extract_output_text(node_result)
                
                # 解析状态并更新
                success = self.state_manager.extract_state_from_agent_output(node_id, output_text)
                
                if success:
                    print(f"   ✅ {node_id} 状态提取成功")
                else:
                    print(f"   ⚠️  {node_id} 状态提取失败，使用fallback")
                    self._apply_fallback_state(node_id)
    
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
        # 简单的fallback状态，直接定义
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


class StatefulGraphBuilder(GraphBuilder):
    """支持状态管理的GraphBuilder"""
    
    def __init__(self):
        super().__init__()
    
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
        
        # 创建StatefulGraph
        return StatefulGraph(
            nodes=self.nodes.copy(), 
            edges=self.edges.copy(), 
            entry_points=self.entry_points.copy()
        )
    
    def add_state_aware_edge(self, from_node, to_node, condition_func: Callable[[StateManager], bool]):
        """添加基于状态的条件边"""
        def state_aware_condition(graph_state: GraphState) -> bool:
            """包装条件函数，注入state_manager访问能力"""
            # 这里需要访问StatefulGraph的state_manager
            # 由于GraphBuilder在build时还没有StatefulGraph实例，我们使用闭包
            return condition_func(None)  # 简化版本，暂时传None
        
        return self.add_edge(from_node, to_node, state_aware_condition)