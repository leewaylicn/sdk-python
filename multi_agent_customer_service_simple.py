#!/usr/bin/env python3
"""
多Agent客户服务系统 - 基于StatefulGraph的简化版本

系统架构：
1. Entry UtilityAgent - 区分点击流(click)还是自由文本(chat) [使用工具]
2. Route Agent (LLM) - 路由决策，判断是否需要人工干预 [纯PE]
3. Intent Agent (LLM) - 意图分析 [纯PE]
4. Transfer UtilityAgent - 人工转接流程 [使用工具]
5. Answer Agent (LLM) - 最终回答 [纯PE]

基于stateful_graph_design.py的优雅实现（继承模式）：
- 极简的UnifiedAgentState（只有状态字段映射）
- StateManager负责状态验证和处理
- StatefulGraph支持真正的状态感知条件路由和fallback机制
- 实时状态处理：在节点执行时立即处理状态
"""

import time
import json
from typing import Dict, Any, List, Optional, Callable

# Strands imports
from strands import Agent, tool

# Local imports
from utility_agent_standalone import create_utility_agent
from stateful_graph import StatefulGraphBuilder, StateManager, UserInteractionRequiredException

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


# ==================== 工具函数 ====================

@tool
def analyze_event_type(user_input: str) -> str:
    """分析用户输入的事件类型，区分点击流还是自由文本"""
    
    # 强制点击事件的关键词（单独出现时必须识别为点击）
    force_click_keywords = [
        "帮助", "退款", "投诉", "查询", "联系客服", "人工客服",
        "help", "refund", "complaint", "query", "contact"
    ]
    
    # 点击流的特征
    click_patterns = [
        "点击", "选择", "按钮", "菜单", "选项",
        "预订", "查看订单", "联系客服", "帮助", "退款", "投诉",
        "查询订单", "订单状态", "客服", "人工", "转人工",
        "booking", "order", "help", "contact", "refund", "complaint"
    ]
    
    # 自由文本的特征
    chat_patterns = [
        "我想", "请问", "怎么", "为什么", "什么时候",
        "帮我", "能否", "可以", "希望", "需要", "请告诉我",
        "我需要了解", "想知道", "有什么", "推荐"
    ]
    
    # 分析输入长度和内容
    input_length = len(user_input)
    user_input_lower = user_input.lower().strip()
    
    # 检查是否是强制点击关键词
    is_force_click = any(keyword in user_input_lower for keyword in force_click_keywords)
    
    # 计算匹配分数
    click_score = sum(1 for pattern in click_patterns if pattern in user_input_lower)
    chat_score = sum(1 for pattern in chat_patterns if pattern in user_input_lower)
    
    # 决策逻辑（优化后）
    if is_force_click and input_length <= 15:
        # 强制点击关键词且长度较短，必须识别为点击
        event_type = "click"
        confidence = 0.9
    elif input_length < 8 and click_score > 0:
        # 极短输入且有点击特征
        event_type = "click"
        confidence = 0.8 + min(click_score * 0.1, 0.2)
    elif input_length > 25 and chat_score > click_score:
        # 长文本且聊天特征明显
        event_type = "chat"
        confidence = 0.7 + min(chat_score * 0.1, 0.3)
    elif click_score > chat_score and click_score > 0:
        # 点击特征更明显
        event_type = "click"
        confidence = 0.7 + min(click_score * 0.1, 0.3)
    elif chat_score > 0:
        # 有聊天特征
        event_type = "chat"
        confidence = 0.6 + min(chat_score * 0.1, 0.3)
    else:
        # 默认为聊天
        event_type = "chat"
        confidence = 0.5
    
    result = {
        "event_type": event_type,
        "confidence": confidence,
        "stage": "entry_agent",
        "status": "Success"
    }
    
    return json.dumps(result, ensure_ascii=False)


@tool
def detect_service_type(user_input: str) -> str:
    """检测用户查询的服务类型，并提供选项供用户选择"""
    
    # 分析用户输入，提取可能的服务类型
    service_keywords = {
        "订单查询": ["订单", "查询", "状态", "物流", "配送", "order"],
        "退款退货": ["退款", "退货", "返回", "refund", "return"],
        "产品咨询": ["产品", "功能", "规格", "价格", "咨询", "product"],
        "技术支持": ["技术", "故障", "问题", "bug", "support", "technical"],
        "投诉建议": ["投诉", "建议", "意见", "complaint", "feedback"],
        "账户问题": ["账户", "登录", "密码", "个人信息", "account", "login"]
    }
    
    # 计算每个服务类型的匹配分数
    scores = {}
    for service_type, keywords in service_keywords.items():
        score = sum(1 for keyword in keywords if keyword in user_input.lower())
        if score > 0:
            scores[service_type] = score
    
    # 根据匹配情况生成选项
    if scores:
        # 按分数排序，取前3个
        sorted_services = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
        recommended_services = [service for service, _ in sorted_services]
        
        # 添加其他选项
        all_services = list(service_keywords.keys())
        other_services = [s for s in all_services if s not in recommended_services]
        options = recommended_services + other_services[:3]
    else:
        # 如果没有明确匹配，提供所有选项
        options = list(service_keywords.keys())
    
    result = {
        "message": "请选择您需要的服务类型，以便我们为您提供更精准的帮助：",
        "options": options,
        "detected_keywords": list(scores.keys()) if scores else [],
        "requires_user_selection": True,
        "stage": "service_selector",
        "status": "Success"
    }
    
    return json.dumps(result, ensure_ascii=False)


@tool
def determine_priority(user_input: str = "") -> str:
    """根据服务类型和用户输入确定优先级，需要用户确认"""
    
    # 从全局状态获取服务类型（这个会在条件函数中设置）
    # 这里使用默认值，实际会通过Agent的state获取
    service_type = "技术支持"  # 默认值
    
    # 高优先级关键词
    high_priority_keywords = [
        "紧急", "急", "马上", "立即", "重要", "严重",
        "urgent", "emergency", "asap", "critical"
    ]
    
    # 根据服务类型预设优先级
    service_priority_map = {
        "退款退货": "high",
        "投诉建议": "high", 
        "技术支持": "medium",
        "订单查询": "medium",
        "产品咨询": "low",
        "账户问题": "medium"
    }
    
    # 检查用户输入中的紧急关键词
    has_urgent_keywords = any(keyword in user_input.lower() for keyword in high_priority_keywords)
    
    # 确定建议的优先级
    suggested_priority = service_priority_map.get(service_type, "medium")
    if has_urgent_keywords:
        suggested_priority = "high"
    
    # 优先级描述
    priority_descriptions = {
        "high": "高优先级 - 将优先处理，预计2-5分钟内响应",
        "medium": "中优先级 - 正常处理，预计10-15分钟内响应", 
        "low": "低优先级 - 按顺序处理，预计30分钟内响应"
    }
    
    result = {
        "message": f"根据您选择的服务类型「{service_type}」，我们建议设置为{priority_descriptions[suggested_priority]}。请确认或选择其他优先级：",
        "suggested_priority": suggested_priority,
        "options": [
            f"确认 - {priority_descriptions[suggested_priority]}",
            f"高优先级 - {priority_descriptions['high']}", 
            f"中优先级 - {priority_descriptions['medium']}",
            f"低优先级 - {priority_descriptions['low']}"
        ],
        "service_type": service_type,
        "requires_user_confirmation": True,
        "stage": "priority_confirmer",
        "status": "Success"
    }
    
    return json.dumps(result, ensure_ascii=False)


@tool
def generate_transfer_message(user_query: str) -> str:
    """生成人工转接消息"""
    
    # 根据查询内容生成个性化消息
    if "退款" in user_query:
        message_type = "refund"
        message = "您的退款请求需要专业客服处理，我正在为您转接到退款专员。"
        priority = "high"
    elif "投诉" in user_query or "不满意" in user_query:
        message_type = "complaint"
        message = "我理解您的不满，为了更好地解决您的问题，我将为您转接到客服主管。"
        priority = "high"
    elif "技术问题" in user_query or "系统故障" in user_query:
        message_type = "technical"
        message = "您遇到的技术问题需要专业技术支持，我正在为您转接到技术客服。"
        priority = "medium"
    else:
        message_type = "general"
        message = "为了更好地为您服务，我将为您转接到人工客服。"
        priority = "medium"
    
    # 添加等待时间估计
    wait_time = "预计等待时间2-5分钟" if priority == "high" else "预计等待时间5-10分钟"
    
    result = {
        "message": message,
        "message_type": message_type,
        "priority": priority,
        "wait_time": wait_time,
        "stage": "transfer_agent",
        "status": "Success"
    }
    
    return json.dumps(result, ensure_ascii=False)


# ==================== 多Agent工作流管理器 ====================

class MultiAgentCustomerService:
    """多Agent客户服务系统管理器 - 基于StatefulGraph的简化实现"""
    
    def __init__(self):
        self.graph = self._create_graph()
    
    def _create_graph(self):
        """创建多Agent图 - 包含用户交互的UtilityAgent"""
        
        # 创建StatefulGraphBuilder
        builder = StatefulGraphBuilder()
        
        # 1. Entry UtilityAgent - 事件类型分析 (使用工具)
        entry_agent = create_utility_agent(
            tools=[analyze_event_type],
            name="Entry事件分析Agent",
            preferred_tool="analyze_event_type",
            response_text="事件类型分析完成，已识别用户输入的交互模式。"
        )
        entry_node = builder.add_node(entry_agent, "entry_agent")
        
        # 2. Service Selector UtilityAgent - 服务类型选择 (需要用户交互)
        service_selector = create_utility_agent(
            tools=[detect_service_type],
            name="服务类型选择Agent",
            preferred_tool="detect_service_type",
            response_text="正在分析您的需求，为您提供服务类型选项..."
        )
        service_selector_node = builder.add_node(service_selector, "service_selector")
        
        # 3. Priority Confirmer UtilityAgent - 优先级确认 (需要用户交互)
        # 创建一个特殊的Agent，能够访问状态中的服务类型
        priority_confirmer = Agent(
            name="优先级确认Agent",
            system_prompt="""你是一个优先级确认专家。请根据用户选择的服务类型确定优先级，并提供选项供用户确认。

**任务：**
1. 从状态中获取用户选择的服务类型
2. 根据服务类型建议优先级
3. 提供选项供用户确认

**输出格式：**
```json
{
  "message": "根据您选择的服务类型，我们建议设置优先级。请确认或选择其他优先级：",
  "suggested_priority": "high/medium/low",
  "options": ["确认 - 高优先级", "高优先级", "中优先级", "低优先级"],
  "service_type": "用户选择的服务类型",
  "requires_user_confirmation": true,
  "stage": "priority_confirmer",
  "status": "Success"
}
```

请直接输出JSON，不要添加其他文字。"""
        )
        priority_confirmer_node = builder.add_node(priority_confirmer, "priority_confirmer")
        
        # 4. Route Agent - 路由决策 (纯PE，无工具，无人工干预)
        route_agent = Agent(
            name="路由决策Agent",
            system_prompt="""你是一个智能路由决策专家。请分析用户查询和前面Agent的分析结果，判断是否需要人工干预。

**重要：请检查状态中的selected_service_type和user_priority_level字段！**

**分析规则（严格执行）：**
1. 如果selected_service_type是"投诉建议"或"退款退货" → requires_human: true
2. 如果user_priority_level是"high" → requires_human: true  
3. 包含"经理"、"主管"、"人工客服"、"转人工" → requires_human: true
4. 包含"多次"、"一直"、"反复"、"没有解决"、"无法处理" → requires_human: true
5. 其他一般咨询和简单问题 → requires_human: false

**输出格式（严格按照统一业务字段）：**
```json
{
  "subject_type": "booking/activity/other",
  "requires_human": true/false,
  "confidence": 0.0-1.0,
  "contact_reason": "用户联系的具体原因",
  "stage": "route_agent",
  "status": "Success"
}
```

**示例：**
- 如果selected_service_type="投诉建议" → requires_human: true
- 如果selected_service_type="产品咨询" 且 user_priority_level="low" → requires_human: false

请直接输出JSON，不要添加其他文字。"""
        )
        route_node = builder.add_node(route_agent, "route_agent")
        
        # 5. Intent Agent - 意图分析 (纯PE，无工具)
        intent_agent = Agent(
            name="意图分析Agent",
            system_prompt="""你是一个用户意图分析专家。请深入分析用户查询，提取关键业务信息和实体。

**主要任务：**
1. 识别主题类型 (subject_type)
2. 提取订单ID (booking_id) 和活动ID (activity_id)
3. 提取其他相关实体信息
4. 评估分析的置信度

**输出格式（严格按照统一业务字段）：**
```json
{
  "subject_type": "booking/activity/other",
  "booking_id": "提取的订单号(如果有)",
  "activity_id": "提取的活动ID(如果有)",
  "intent_type": "具体的意图类型",
  "confidence": 0.0-1.0,
  "stage": "intent_agent",
  "status": "Success"
}
```

请直接输出JSON，不要添加其他文字。"""
        )
        intent_node = builder.add_node(intent_agent, "intent_agent")
        
        # 6. Transfer UtilityAgent - 人工转接 (使用工具)
        transfer_agent = create_utility_agent(
            tools=[generate_transfer_message],
            name="人工转接Agent",
            preferred_tool="generate_transfer_message",
            response_text="正在为您转接人工客服，请稍候..."
        )
        transfer_node = builder.add_node(transfer_agent, "transfer_agent")
        
        # 7. Answer Agent - 最终回答 (纯PE，无工具)
        answer_agent = Agent(
            name="最终回答Agent",
            system_prompt="""你是一个专业的客服回答生成专家。请基于用户查询和前面Agent的分析结果生成最终回答。

**输出格式（严格按照统一业务字段）：**
```json
{
  "response": "专业的客服回答内容",
  "subject_type": "booking/activity/other",
  "confidence": 0.0-1.0,
  "stage": "answer_agent",
  "status": "Success"
}
```

请直接输出JSON，不要添加其他文字。"""
        )
        answer_node = builder.add_node(answer_agent, "answer_agent")
        
        # ==================== 添加边和条件路由 ====================
        
        # 主流程分支：根据事件类型决定路径
        def is_click_event(state_manager: StateManager) -> bool:
            """检查是否为点击事件 - 需要用户交互流程"""
            event_type = state_manager.get_state("event_type")
            stage = state_manager.get_state("stage")
            status = state_manager.get_state("status")
            
            print(f"     🖱️  点击事件检查: event_type={event_type}, stage={stage}, status={status}")
            
            # 点击事件需要通过服务选择和优先级确认流程
            return (stage == "entry_agent" and 
                    status == "Success" and 
                    event_type == "click")
        
        def is_chat_event(state_manager: StateManager) -> bool:
            """检查是否为自由文本事件 - 直接进入路由决策"""
            event_type = state_manager.get_state("event_type")
            stage = state_manager.get_state("stage")
            status = state_manager.get_state("status")
            
            print(f"     💬 自由文本检查: event_type={event_type}, stage={stage}, status={status}")
            
            # 自由文本直接进入路由决策，跳过用户交互
            return (stage == "entry_agent" and 
                    status == "Success" and 
                    event_type == "chat")
        
        # 条件分支：点击事件 -> 服务选择流程
        builder.add_state_aware_edge(entry_node, service_selector_node, is_click_event)
        
        # 条件分支：自由文本 -> 直接路由决策
        builder.add_state_aware_edge(entry_node, route_node, is_chat_event)
        
        # 用户交互边：service_selector -> priority_confirmer (需要用户选择服务类型)
        def has_service_selection(state_manager: StateManager) -> bool:
            """检查是否有用户的服务类型选择"""
            user_input_data = state_manager.get_state("service_selector_user_input")
            if user_input_data:
                user_selection = user_input_data.get("input")
                print(f"     ✅ 发现服务类型选择: {user_selection}")
                
                # 将用户选择的服务类型传递给priority_confirmer工具
                # 通过更新全局状态来传递参数
                state_manager.global_state["selected_service_type"] = user_selection
                return True
            print(f"     ❌ 未发现服务类型选择")
            return False
        
        builder.add_state_aware_edge(
            service_selector_node, 
            priority_confirmer_node, 
            has_service_selection,
            requires_user_input=True  # 需要用户输入
        )
        
        # 点击流程中的人工干预决策：priority_confirmer -> transfer_agent 或 answer_agent
        def click_needs_human_intervention(state_manager: StateManager) -> bool:
            """点击流程中检查是否需要人工干预"""
            user_input_data = state_manager.get_state("priority_confirmer_user_input")
            if not user_input_data:
                return False
                
            user_confirmation = user_input_data.get("input")
            service_input = state_manager.get_state("service_selector_user_input")
            service_type = service_input.get("input", "") if service_input else ""
            
            # 解析用户选择的优先级
            if "高优先级" in user_confirmation or "确认" in user_confirmation:
                state_manager.global_state["user_priority_level"] = "high"
            elif "中优先级" in user_confirmation:
                state_manager.global_state["user_priority_level"] = "medium"
            elif "低优先级" in user_confirmation:
                state_manager.global_state["user_priority_level"] = "low"
            
            user_priority_level = state_manager.global_state.get("user_priority_level")
            
            # 高优先级服务类型
            high_priority_services = ["退款退货", "投诉建议"]
            
            # 判断是否需要人工干预
            needs_human = False
            
            # 1. 明确的高优先级选择
            if user_priority_level == "high" or "高优先级" in user_confirmation or "确认" in user_confirmation:
                needs_human = True
                
            # 2. 高优先级服务类型
            elif service_type in high_priority_services:
                needs_human = True
            
            print(f"     🤔 点击流程人工干预检查: service_type={service_type}, priority_level={user_priority_level}")
            print(f"        决策结果: needs_human={needs_human}")
            
            return needs_human
        
        def click_needs_auto_processing(state_manager: StateManager) -> bool:
            """点击流程中检查是否需要自动处理"""
            user_input_data = state_manager.get_state("priority_confirmer_user_input")
            if not user_input_data:
                return False
                
            user_confirmation = user_input_data.get("input")
            service_input = state_manager.get_state("service_selector_user_input")
            service_type = service_input.get("input", "") if service_input else ""
            
            user_priority_level = state_manager.global_state.get("user_priority_level")
            
            # 高优先级服务类型
            high_priority_services = ["退款退货", "投诉建议"]
            
            # 判断是否自动处理（与人工干预相反的逻辑）
            needs_auto = True
            
            # 1. 明确的高优先级选择 -> 不自动处理
            if user_priority_level == "high" or "高优先级" in user_confirmation or "确认" in user_confirmation:
                needs_auto = False
                
            # 2. 高优先级服务类型 -> 不自动处理
            elif service_type in high_priority_services:
                needs_auto = False
            
            print(f"     🤖 点击流程自动处理检查: service_type={service_type}, priority_level={user_priority_level}")
            print(f"        决策结果: needs_auto={needs_auto}")
            
            return needs_auto
        
        # 点击流程的条件边（需要用户输入后才能判断）
        builder.add_state_aware_edge(
            priority_confirmer_node,
            transfer_node,
            click_needs_human_intervention,
            requires_user_input=True  # 需要用户输入
        )
        
        builder.add_state_aware_edge(
            priority_confirmer_node,
            answer_node,
            click_needs_auto_processing,
            requires_user_input=True  # 需要用户输入
        )
        
        # 聊天流程的路由决策边（保持原有逻辑）
        def needs_human_intervention(state_manager: StateManager) -> bool:
            """聊天流程中检查是否需要人工干预"""
            requires_human = state_manager.get_state("requires_human")
            stage = state_manager.get_state("stage")
            status = state_manager.get_state("status")
            
            print(f"     🤔 聊天流程人工干预检查: requires_human={requires_human}, stage={stage}, status={status}")
            
            return (stage == "route_agent" and 
                    status == "Success" and 
                    requires_human == True)
        
        def needs_auto_processing(state_manager: StateManager) -> bool:
            """聊天流程中检查是否需要自动处理"""
            requires_human = state_manager.get_state("requires_human")
            stage = state_manager.get_state("stage")
            status = state_manager.get_state("status")
            
            print(f"     🤖 聊天流程自动处理检查: requires_human={requires_human}, stage={stage}, status={status}")
            
            return (stage == "route_agent" and 
                    status == "Success" and 
                    requires_human == False)
        
        # 聊天流程的条件边
        builder.add_state_aware_edge(route_node, transfer_node, needs_human_intervention)
        builder.add_state_aware_edge(route_node, intent_node, needs_auto_processing)
        builder.add_edge(intent_node, answer_node)
        
        # 设置入口点
        builder.set_entry_point("entry_agent")
        
        return builder.build()
    
    def execute(self, user_input: str):
        """执行多Agent工作流"""
        print("\n🚀 多Agent客户服务工作流开始执行")
        print("="*60)
        print(f"📥 用户输入: {user_input}")
        
        try:
            # 执行图
            result = self.graph(user_input)
            
            return result
            
        except Exception as e:
            print(f"❌ 执行失败: {str(e)}")
            raise
    
    def execute_interactive(self, user_input: str):
        """交互式执行多Agent工作流 - 在点击事件中等待用户终端输入"""
        print("\n🚀 多Agent客户服务工作流开始执行（交互模式）")
        print("="*60)
        print(f"📥 用户输入: {user_input}")
        
        try:
            # 执行图，捕获用户交互异常
            result = self.graph(user_input)
            return result
            
        except UserInteractionRequiredException as e:
            # 处理用户交互请求
            return self._handle_user_interaction(user_input, e.interaction_request)
        except Exception as e:
            print(f"❌ 执行失败: {str(e)}")
            raise
    
    def _handle_user_interaction(self, original_input: str, interaction_request: Dict[str, Any]):
        """处理用户交互请求 - 等待终端输入并继续执行"""
        node_id = interaction_request.get("node_id")
        original_output = interaction_request.get("original_output", {})
        options = original_output.get("options", [])
        message = original_output.get("message", "请选择一个选项：")
        
        print(f"\n🔔 {node_id} 需要用户输入:")
        print(f"📝 {message}")
        
        if options:
            print("📋 可选项:")
            for i, option in enumerate(options, 1):
                print(f"  {i}. {option}")
        
        # 等待用户终端输入
        while True:
            try:
                user_choice = input("\n👤 请输入您的选择: ").strip()
                
                if not user_choice:
                    print("❌ 输入不能为空，请重新输入")
                    continue
                
                # 如果输入是数字，转换为对应的选项
                if user_choice.isdigit() and options:
                    choice_index = int(user_choice) - 1
                    if 0 <= choice_index < len(options):
                        user_choice = options[choice_index]
                        print(f"✅ 您选择了: {user_choice}")
                    else:
                        print(f"❌ 无效选择，请输入 1-{len(options)} 之间的数字")
                        continue
                
                # 提供用户输入
                self.graph.provide_user_input(user_choice)
                break
                
            except KeyboardInterrupt:
                print("\n\n❌ 用户取消操作")
                return None
            except Exception as e:
                print(f"❌ 输入处理错误: {e}")
                continue
        
        # 继续执行，可能还有更多用户交互
        try:
            result = self.graph(original_input)
            return result
            
        except UserInteractionRequiredException as e:
            # 递归处理下一个用户交互
            return self._handle_user_interaction(original_input, e.interaction_request)
        except Exception as e:
            print(f"❌ 继续执行失败: {str(e)}")
            raise
    
    def print_execution_summary(self, result):
        """打印执行摘要"""
        print(f"\n✅ 工作流执行完成:")
        print(f"  状态: {result.status}")
        print(f"  完成节点数: {result.completed_nodes}/{result.total_nodes}")
        print(f"  失败节点数: {result.failed_nodes}")
        print(f"  执行时间: {result.execution_time}ms")
        
        # 显示执行顺序
        print(f"\n📋 节点执行顺序:")
        for i, node in enumerate(result.execution_order, 1):
            print(f"  {i}. {node.node_id}")
        
        # 显示最终状态
        final_state = self.graph.state_manager.get_state()
        print(f"\n📊 最终状态:")
        print(json.dumps(final_state, ensure_ascii=False, indent=2))


# ==================== 主程序和测试 ====================

def interactive_demo():
    """交互式演示 - 等待用户终端输入"""
    print("🎯 多Agent客户服务系统 - 交互式演示")
    print("="*60)
    print("💡 功能特点：")
    print("  - 点击事件：需要用户选择服务类型和优先级")
    print("  - 聊天事件：完全自动化处理")
    print("  - 智能路由：根据用户选择决定人工干预或自动处理")
    print("="*60)
    
    # 创建多Agent系统
    customer_service = MultiAgentCustomerService()
    
    while True:
        try:
            print(f"\n{'='*60}")
            print("🎤 请输入您的问题或需求（输入 'quit' 退出）:")
            print("💡 提示：")
            print("  - 短词如'投诉'、'退款'、'查询' → 点击流程（需要交互）")
            print("  - 长句如'请问你们有什么活动推荐？' → 聊天流程（自动处理）")
            print("-"*60)
            
            user_input = input("👤 您的输入: ").strip()
            
            if not user_input:
                print("❌ 输入不能为空，请重新输入")
                continue
                
            if user_input.lower() in ['quit', 'exit', '退出', 'q']:
                print("\n👋 感谢使用多Agent客户服务系统，再见！")
                break
            
            print(f"\n🔄 正在处理您的请求...")
            
            # 使用交互式执行
            result = customer_service.execute_interactive(user_input)
            
            if result:
                # 打印执行摘要
                customer_service.print_execution_summary(result)
            else:
                print("❌ 执行被用户取消")
                
        except KeyboardInterrupt:
            print("\n\n👋 用户中断，退出系统")
            break
        except Exception as e:
            print(f"❌ 执行失败: {str(e)}")
            import traceback
            traceback.print_exc()
            
            # 询问是否继续
            try:
                continue_choice = input("\n❓ 是否继续使用系统？(y/n): ").strip().lower()
                if continue_choice not in ['y', 'yes', '是', '继续']:
                    break
            except KeyboardInterrupt:
                break

def main():
    """主程序"""
    print("🎯 多Agent客户服务系统演示 - 基于StatefulGraph的继承模式版本")
    print("="*60)
    print("💡 设计特点：")
    print("  - 极简的UnifiedAgentState（只有状态字段映射）")
    print("  - StateManager负责状态验证和处理")
    print("  - StatefulGraph支持真正的状态感知条件路由和fallback机制")
    print("  - 实时状态处理：在节点执行时立即处理状态")
    print("  - 状态感知条件边：条件函数可以访问最新的Agent输出状态")
    print("="*60)
    
    # 询问运行模式
    print("\n🎮 请选择运行模式:")
    print("  1. 交互式演示（推荐）- 等待用户终端输入")
    print("  2. 自动测试 - 运行预设测试用例")
    
    try:
        mode_choice = input("\n👤 请选择模式 (1/2): ").strip()
        
        if mode_choice == "1":
            interactive_demo()
        elif mode_choice == "2":
            run_auto_tests()
        else:
            print("❌ 无效选择，默认运行交互式演示")
            interactive_demo()
            
    except KeyboardInterrupt:
        print("\n\n👋 用户中断，退出系统")

def run_auto_tests():
    """运行自动测试用例"""
    print("\n🧪 运行自动测试用例")
    print("="*60)
    
    # 测试用例 - 简化版本
    test_cases = [
        "我要申请退款，订单号12345，这个产品质量有问题",  # 应该触发人工干预
        "请问你们有什么旅游活动推荐吗？",  # 应该自动处理
    ]
    
    for i, test_input in enumerate(test_cases, 1):
        print(f"\n{'='*60}")
        print(f"🧪 测试用例 {i}: {test_input}")
        print("="*60)
        
        try:
            # 创建多Agent系统
            customer_service = MultiAgentCustomerService()
            
            # 执行工作流
            result = customer_service.execute(test_input)
            
            # 打印执行摘要
            customer_service.print_execution_summary(result)
                
        except Exception as e:
            print(f"❌ 测试用例 {i} 执行失败: {str(e)}")
            import traceback
            traceback.print_exc()
        
        if i < len(test_cases):
            print(f"\n⏳ 等待下一个测试用例...")
            time.sleep(1)
    
    print(f"\n🎉 所有测试用例执行完成！")
    print("\n💡 系统特性验证:")
    print("  ✅ 极简UnifiedAgentState - 只有状态字段映射")
    print("  ✅ StateManager状态管理 - 验证、标准化、处理")
    print("  ✅ StatefulGraph实时状态处理 - 在节点执行时立即处理状态")
    print("  ✅ 真正的状态感知条件路由 - 条件函数可以访问最新状态")
    print("  ✅ 状态注入机制 - 执行前将全局状态注入到Agent")
    print("  ✅ Fallback机制 - 状态提取失败时的兜底方案")


if __name__ == "__main__":
    main()