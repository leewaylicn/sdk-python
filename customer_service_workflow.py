"""
客服场景多Agent混合编排系统 - 基于Strands Graph实现

简化版工作流，展示三种Agent类型：
1. 主Agent - 使用标准Agent进行意图分类
2. UtilityAgent - 使用UtilityAgent进行情感分析
3. 人工交接Agent - 使用handoff_to_user进行人工干预

支持人机协作(Human-in-the-loop)功能。
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional, Callable, Union

# 导入Strands相关库
from strands import Agent, tool
from strands.multiagent.graph import GraphBuilder
from strands.session.file_session_manager import FileSessionManager
from strands.session.ddb_session_manager import DDBSessionManager

# 正确导入handoff_to_user工具
from strands_tools import handoff_to_user

import uuid

from utility_agent import UtilityAgent

# 设置日志
logger = logging.getLogger(__name__)


# 定义工具函数
@tool
def classify_intent(query: str) -> str:
    """分析用户意图，识别是咨询、投诉、退款请求等"""
    intent_types = ["general_inquiry", "product_inquiry", "complaint", "refund_request", "technical_support"]
    keywords = {
        "general_inquiry": ["什么是", "怎么样", "有哪些", "介绍"],
        "product_inquiry": ["产品", "价格", "功能", "规格", "配置"],
        "complaint": ["投诉", "不满", "差评", "问题", "失望"],
        "refund_request": ["退款", "退货", "取消订单", "不想要了", "返还"],
        "technical_support": ["故障", "不工作", "错误", "修复", "帮助解决"]
    }
    
    # 默认为一般咨询
    result = {
        "intent": "general_inquiry",
        "confidence": 0.6,
        "keywords": [],
        "complexity": "medium"
    }
    
    # 检查每种意图的关键词
    max_matches = 0
    for intent, intent_keywords in keywords.items():
        matches = sum(1 for keyword in intent_keywords if keyword in query)
        if matches > max_matches:
            max_matches = matches
            result["intent"] = intent
            result["confidence"] = min(0.5 + 0.1 * matches, 0.95)
    
    # 提取匹配的关键词
    for keyword in keywords[result["intent"]]:
        if keyword in query:
            result["keywords"].append(keyword)
    
    # 判断复杂度
    if len(query) > 100 or "复杂" in query or "多个问题" in query:
        result["complexity"] = "high"
    elif len(query) < 20 and max_matches <= 1:
        result["complexity"] = "low"
    
    return json.dumps(result, ensure_ascii=False)


@tool
def analyze_sentiment(query: str) -> str:
    """分析用户情绪，判断是积极、中性还是负面"""
    positive_words = ["谢谢", "感谢", "满意", "好", "棒", "喜欢", "赞", "优秀"]
    negative_words = ["不满", "差", "糟糕", "失望", "退款", "投诉", "生气", "恼火", "垃圾"]
    extreme_negative = ["非常不满", "极其失望", "太差了", "完全不行", "彻底失败"]
    
    # 计算情感分数
    sentiment_score = 0
    for word in positive_words:
        if word in query:
            sentiment_score += 1
    
    for word in negative_words:
        if word in query:
            sentiment_score -= 1
    
    for phrase in extreme_negative:
        if phrase in query:
            sentiment_score -= 3
    
    # 对于包含"退款"的请求，强制设置为需要人工干预
    if "退款" in query:
        sentiment_score = min(sentiment_score - 2, -2)  # 确保退款请求被标记为负面
    
    # 对于包含"退款"和"多次"或"一直"的请求，强制设置为需要人工干预
    if "退款" in query and ("多次" in query or "一直" in query or "没有解决" in query):
        sentiment_score = -5
    
    # 确定情感类别
    if sentiment_score >= 2:
        sentiment = "positive"
    elif sentiment_score <= -2:
        sentiment = "negative"
    else:
        sentiment = "neutral"
    
    # 检查是否需要人工干预
    requires_human = False
    reason = ""
    if sentiment_score <= -2:
        requires_human = True
        if "退款" in query:
            reason = "用户提出退款要求，需要人工客服处理退款流程"
        else:
            reason = "用户情绪负面，建议人工客服介入"
    
    # 对于包含"退款"和"多次"或"一直"的请求，强制设置为需要人工干预
    if "退款" in query and ("多次" in query or "一直" in query or "没有解决" in query):
        requires_human = True
        reason = "用户多次请求退款未得到解决，需要人工客服优先处理"
    
    result = {
        "sentiment": sentiment,
        "score": sentiment_score,
        "requires_human": requires_human,
        "reason": reason
    }
    
    return json.dumps(result, ensure_ascii=False)

@tool
def retrieve_knowledge(query: str, intent: str) -> str:
    """从知识库中检索相关信息"""
    # 模拟知识库查询
    knowledge_base = {
        "general_inquiry": {
            "response": "我们是一家专注于提供高质量产品和服务的公司。我们的客服团队7x24小时为您服务。",
            "confidence": 0.9
        },
        "product_inquiry": {
            "response": "我们的产品种类丰富，包括电子产品、家居用品和生活用品等。每件产品都有详细的规格说明和用户评价。",
            "confidence": 0.85
        },
        "complaint": {
            "response": "我们非常重视您的反馈，并致力于解决您遇到的问题。请提供更多细节，以便我们能更好地帮助您。",
            "confidence": 0.8
        },
        "refund_request": {
            "response": "根据我们的退款政策，购买后30天内未使用的产品可以申请全额退款。已使用的产品需要根据使用情况评估退款金额。",
            "confidence": 0.9
        },
        "technical_support": {
            "response": "对于技术问题，我们建议先查看产品说明书或访问我们的在线帮助中心。如果问题仍未解决，请联系技术支持团队。",
            "confidence": 0.85
        }
    }
    
    # 解析意图
    try:
        intent_data = json.loads(intent)
        intent_type = intent_data.get("intent", "general_inquiry")
    except:
        intent_type = "general_inquiry"
    
    # 检查是否有匹配的知识
    if intent_type in knowledge_base:
        knowledge_found = True
        response = knowledge_base[intent_type]["response"]
        confidence = knowledge_base[intent_type]["confidence"]
    else:
        knowledge_found = False
        response = "抱歉，我没有找到与您问题相关的信息。"
        confidence = 0.3
    
    # 检查是否需要人工干预
    requires_human = False
    reason = ""
    if not knowledge_found or confidence < 0.5:
        requires_human = True
        reason = "无法找到相关知识或置信度过低，建议人工客服介入"
    
    result = {
        "knowledge_found": knowledge_found,
        "response": response,
        "confidence": confidence,
        "requires_human": requires_human,
        "reason": reason
    }
    
    return json.dumps(result, ensure_ascii=False)


def create_session_manager(session_id, use_ddb=False):
    """创建会话管理器
    
    Args:
        session_id: 会话ID
        use_ddb: 是否使用DynamoDB作为存储后端
        
    Returns:
        会话管理器实例
    """
    if use_ddb:
        # 使用环境变量或默认值配置DynamoDB
        table_name = os.environ.get("DDB_SESSION_TABLE", "strands-sessions")
        region_name = os.environ.get("AWS_REGION", "us-west-2")
        ttl_seconds = int(os.environ.get("DDB_SESSION_TTL", "86400"))  # 默认24小时
        
        return DDBSessionManager(
            session_id=session_id,
            table_name=table_name,
            region_name=region_name,
            ttl_seconds=ttl_seconds
        )
    else:
        return FileSessionManager(session_id=session_id)


def create_customer_service_workflow(session_id=None, use_ddb=False):
    """创建客服场景多Agent Graph工作流
    
    Args:
        session_id: 会话ID，如果为None则生成新的会话ID
        use_ddb: 是否使用DynamoDB作为存储后端
    """
    
    # 如果没有提供会话ID，则生成一个新的
    if session_id is None:
        session_id = f"customer-service-{uuid.uuid4()}"
    
    # 创建会话管理器
    session_manager = create_session_manager(session_id, use_ddb)
    
    # 定义模型
    bedrock_model = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    
    # 1. 创建意图分类代理 - 参考travel_advisor_agent模式
    intent_classifier_agent = Agent(
        model=bedrock_model,
        tools=[classify_intent],
        system_prompt="""你是一个客服意图分析专家，负责分析用户问题的意图和类型。
        - 使用classify_intent工具分析用户输入的意图、置信度和复杂度
        - 准确识别是咨询、投诉、退款请求还是技术支持等类型""",
        name="意图分类代理"
    )
    
    # 2. 创建情感分析代理 - 使用UtilityAgent（不需要人工干预）
    sentiment_utility_agent = UtilityAgent(
        tools=[analyze_sentiment],
        name="情感分析代理",
        description="分析用户情绪状态的实用代理",
        response_text="""基于情感分析结果，我的评估如下：

情绪分析已完成。系统已识别用户的情绪状态和强度。

【无需人工干预】""",  # 固定为无需人工干预
        preferred_tool="analyze_sentiment"
    )
    
    # 使用UtilityAgent内部的agent来兼容GraphBuilder
    sentiment_analysis_agent = sentiment_utility_agent.agent

    # 3. 创建知识库查询代理 - 保留人工干预功能
    knowledge_retrieval_agent = Agent(
        model=bedrock_model,
        tools=[retrieve_knowledge],
        system_prompt="""你是一个知识库查询专家，负责从知识库中检索相关信息。
        - 使用retrieve_knowledge工具根据用户意图查询相关解决方案
        - 评估知识库答案的置信度，判断是否需要人工干预

重要：在你的回复中，必须明确说明是否需要人工干预：
- 如果需要人工干预，在回复末尾添加：【需要人工干预】
- 如果不需要人工干预，在回复末尾添加：【无需人工干预】

这个标识将用于工作流的路由决策。""",
        name="知识库查询代理"
    )
    
    # 4. 创建人工交接代理 - 强制调用工具版本
    human_handoff_agent = Agent(
        model=bedrock_model,
        tools=[handoff_to_user],
        system_prompt="""你是人工客服交接确认专家。你的任务是使用handoff_to_user工具与用户确认是否需要转接人工客服。

**重要：你必须调用handoff_to_user工具，不能只给出文本回复**

工作流程：
1. 分析前面Agent的处理结果
2. 必须调用handoff_to_user工具
3. 在工具调用中设置合适的消息和参数

**工具调用要求：**
- 工具名称：handoff_to_user
- 参数设置：
  * message: "根据分析，您的问题需要人工客服处理。请问您是否同意转接人工客服？请回复'是'或'否'"
  * breakout_of_loop: false

**示例调用：**
```
handoff_to_user(
    message="根据分析，您的问题需要人工客服处理。请问您是否同意转接人工客服？请回复'是'或'否'",
    breakout_of_loop=false
)
```

**关键要求：**
- 必须调用handoff_to_user工具
- 不要只给出文本回复
- 使用breakout_of_loop=false等待用户确认""",
        name="人工干预"
    )
    
    # 创建图构建器
    builder = GraphBuilder()
    
    # 添加节点 - 混合使用Agent和UtilityAgent
    intent_node = builder.add_node(intent_classifier_agent, "intent_classifier")
    sentiment_node = builder.add_node(sentiment_analysis_agent, "sentiment_analysis")  # UtilityAgent
    knowledge_node = builder.add_node(knowledge_retrieval_agent, "knowledge_retrieval")
    handoff_node = builder.add_node(human_handoff_agent, "human_handoff")
    
    # 简化的条件判断函数 - 更新路由逻辑
    def should_go_to_knowledge(state):
        """判断是否应该进入知识库查询 - 现在总是进入，因为sentiment不再触发人工干预"""
        return True  # 总是进入知识库查询
    
    def should_go_to_human_from_sentiment(state):
        """从情感分析直接到人工干预的条件 - 现在不再使用此路径"""
        return False  # sentiment_analysis_agent不再触发人工干预
    
    def should_go_to_human_from_knowledge(state):
        """从知识库查询到人工干预的条件"""
        if "knowledge_retrieval" in state.results:
            result = state.results["knowledge_retrieval"]
            if result and hasattr(result, 'result') and hasattr(result.result, 'message'):
                message_content = str(result.result.message)
                return "需要人工干预" in message_content
        return False
    
    # 构建简化的多Agent Graph工作流
    # 1. 意图分类代理 -> 情感分析代理（总是执行）
    builder.add_edge(intent_node, sentiment_node, condition=lambda state: True)
    
    # 2. 情感分析代理 -> 知识库查询代理（总是执行，因为sentiment不再触发人工干预）
    builder.add_edge(sentiment_node, knowledge_node, condition=should_go_to_knowledge)
    
    # 3. 知识库查询代理 -> 人工交接代理（如果知识库无法解决问题）
    builder.add_edge(knowledge_node, handoff_node, condition=should_go_to_human_from_knowledge)
    
    # 设置入口点
    builder.set_entry_point("intent_classifier")
    
    # 构建图
    return builder.build()


def demo_workflow(use_ddb=False, session_id=None):
    """演示工作流
    
    Args:
        use_ddb: 是否使用DynamoDB作为存储后端
        session_id: 会话ID，如果为None则生成新的会话ID
    """
    # 如果没有提供会话ID，则生成一个新的
    if session_id is None:
        session_id = f"customer-service-demo-{uuid.uuid4()}"
    
    print("=" * 60)
    print("客服场景多Agent混合编排系统演示")
    print(f"会话ID: {session_id}")
    print(f"存储后端: {'DynamoDB' if use_ddb else '文件系统'}")
    print("=" * 60)
    
    # 用户输入
    user_input = "我上个月买的产品有质量问题，我已经联系过你们的客服多次但没有得到解决。我现在要求全额退款，并且希望有人能解释为什么这个问题一直没有得到妥善处理。我非常不满意你们的服务！"
    
    print(f"用户输入: {user_input}")
    print("-" * 60)
    
    # 创建工作流图
    workflow_graph = create_customer_service_workflow(session_id=session_id, use_ddb=use_ddb)
    
    print("工作流图创建成功")
    print(f"节点数量: {len(workflow_graph.nodes)}")
    print(f"边数量: {len(workflow_graph.edges)}")
    
    try:
        print("\n开始执行工作流...")
        
        # 执行工作流
        graph_result = workflow_graph(user_input)
        
        print(f"\n工作流执行完成:")
        print(f"状态: {graph_result.status}")
        print(f"执行节点数: {graph_result.completed_nodes}")
        print(f"失败节点数: {graph_result.failed_nodes}")
        print(f"执行时间: {graph_result.execution_time}ms")
        
        # 显示节点结果
        print(f"\n节点执行结果:")
        for node_id, result in graph_result.results.items():
            print(f"节点 {node_id}: {str(result)[:100]}...")
        
        # 检查是否触发了人工干预
        if "human_handoff" in graph_result.results:
            print("\n✅ 人工干预成功触发!")
            # 显示人工干预的详细信息
            handoff_result = graph_result.results["human_handoff"]
            if handoff_result and hasattr(handoff_result, 'result'):
                print(f"人工干预详情: {handoff_result.result}")
        else:
            print("\n❌ 人工干预未触发")
        
        # 显示会话持久化信息
        print(f"\n会话持久化信息:")
        print(f"会话ID: {session_id}")
        print(f"存储后端: {'DynamoDB' if use_ddb else '文件系统'}")
        print(f"要继续此会话，请使用相同的session_id")
        
    except Exception as e:
        print(f"\n❌ 工作流执行失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import argparse
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="客服场景多Agent混合编排系统演示")
    parser.add_argument("--ddb", action="store_true", help="使用DynamoDB作为存储后端")
    parser.add_argument("--session-id", help="会话ID，如果不提供则生成新的会话ID")
    parser.add_argument("--table-name", help="DynamoDB表名，默认为strands-sessions")
    parser.add_argument("--region", help="AWS区域，默认为us-west-2")
    
    args = parser.parse_args()
    
    # 设置环境变量
    if args.table_name:
        os.environ["DDB_SESSION_TABLE"] = args.table_name
    if args.region:
        os.environ["AWS_REGION"] = args.region
    
    # 运行演示
    demo_workflow(use_ddb=args.ddb, session_id=args.session_id)