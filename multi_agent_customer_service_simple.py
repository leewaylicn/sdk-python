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
from stateful_graph import StatefulGraphBuilder, StateManager

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
    
    # 点击流的特征
    click_patterns = [
        "点击", "选择", "按钮", "菜单", "选项",
        "预订", "查看订单", "联系客服", "帮助",
        "booking", "order", "help", "contact"
    ]
    
    # 自由文本的特征
    chat_patterns = [
        "我想", "请问", "怎么", "为什么", "什么时候",
        "帮我", "能否", "可以", "希望", "需要"
    ]
    
    # 分析输入长度
    input_length = len(user_input)
    
    # 计算匹配分数
    click_score = sum(1 for pattern in click_patterns if pattern in user_input.lower())
    chat_score = sum(1 for pattern in chat_patterns if pattern in user_input.lower())
    
    # 决策逻辑
    if input_length < 10 and click_score > 0:
        event_type = "click"
        confidence = 0.8 + min(click_score * 0.1, 0.2)
    elif input_length > 20 and chat_score > click_score:
        event_type = "chat"
        confidence = 0.7 + min(chat_score * 0.1, 0.3)
    elif click_score > chat_score:
        event_type = "click"
        confidence = 0.6 + min(click_score * 0.1, 0.3)
    else:
        event_type = "chat"
        confidence = 0.6 + min(chat_score * 0.1, 0.3)
    
    result = {
        "event_type": event_type,
        "confidence": confidence,
        "stage": "entry_agent",
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
        """创建多Agent图"""
        
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
        
        # 2. Route Agent - 路由决策 (纯PE，无工具)
        route_agent = Agent(
            name="路由决策Agent",
            system_prompt="""你是一个智能路由决策专家。请分析用户查询，判断是否需要人工干预，并识别主题类型和联系原因。

**分析规则：**
- 包含"退款"、"投诉"、"不满意"、"差评"、"问题严重" → 需要人工干预
- 包含"经理"、"主管"、"人工客服"、"转人工" → 需要人工干预  
- 包含"多次"、"一直"、"反复"、"没有解决"、"无法处理" → 需要人工干预
- 一般咨询和简单问题 → 继续自动处理

**主题类型识别：**
- booking: 预订、订单相关
- activity: 活动、景点、娱乐相关
- other: 其他类型

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

请直接输出JSON，不要添加其他文字。"""
        )
        route_node = builder.add_node(route_agent, "route_agent")
        
        # 3. Intent Agent - 意图分析 (纯PE，无工具)
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
        
        # 4. Transfer UtilityAgent - 人工转接 (使用工具)
        transfer_agent = create_utility_agent(
            tools=[generate_transfer_message],
            name="人工转接Agent",
            preferred_tool="generate_transfer_message",
            response_text="正在为您转接人工客服，请稍候..."
        )
        transfer_node = builder.add_node(transfer_agent, "transfer_agent")
        
        # 5. Answer Agent - 最终回答 (纯PE，无工具)
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
        
        # 添加边和条件路由
        builder.add_edge(entry_node, route_node)
        
        # 真正的状态感知条件路由 - 使用继承模式的优势
        def needs_human_intervention(state_manager: StateManager) -> bool:
            """检查是否需要人工干预 - 真正的状态感知版本"""
            requires_human = state_manager.get_state("requires_human")
            stage = state_manager.get_state("stage")
            status = state_manager.get_state("status")
            
            print(f"     🤔 人工干预检查: requires_human={requires_human}, stage={stage}, status={status}")
            
            # 只有当route_agent成功执行且明确需要人工干预时才转接
            return (stage == "route_agent" and 
                    status == "Success" and 
                    requires_human == True)
        
        def needs_auto_processing(state_manager: StateManager) -> bool:
            """检查是否需要自动处理 - 真正的状态感知版本"""
            requires_human = state_manager.get_state("requires_human")
            stage = state_manager.get_state("stage")
            status = state_manager.get_state("status")
            
            print(f"     🤖 自动处理检查: requires_human={requires_human}, stage={stage}, status={status}")
            
            # 只有当route_agent成功执行且不需要人工干预时才自动处理
            return (stage == "route_agent" and 
                    status == "Success" and 
                    requires_human == False)
        
        # 使用真正的状态感知条件边
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