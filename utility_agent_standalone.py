#!/usr/bin/env python3
"""
UtilityAgent - 独立实现版本

专注于工具函数执行的智能代理，继承自Strands Agent。
通过Mock模型直接执行工具，绕过LLM推理，支持完整的session管理功能。
"""

import asyncio
import json
import random
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional, Callable, Union

# Strands imports
from strands import Agent
from strands.models.model import Model
from strands.agent.state import AgentState
from strands.session.session_manager import SessionManager

# Local imports
from auto_mock_model import AutoMockToolCallingModel, create_smart_input_generator


class EnhancedAutoMockModel(AutoMockToolCallingModel):
    """
    增强版的AutoMockToolCallingModel，支持优先工具选择和自动终止
    """
    
    def __init__(
        self,
        model_id: str = "enhanced-auto-mock",
        response_text: str = "正在处理您的请求...",
        auto_input_generator: Optional[Callable] = None,
        auto_terminate: bool = True,
        preferred_tool: Optional[str] = None,
        max_tool_calls: int = 2,
        **kwargs
    ):
        """
        初始化增强版模型
        
        Args:
            model_id: 模型ID
            response_text: 响应文本
            auto_input_generator: 自定义输入生成器
            auto_terminate: 是否自动终止工具调用循环
            preferred_tool: 优先使用的工具名称
            max_tool_calls: 最大工具调用次数
            **kwargs: 其他参数
        """
        super().__init__(
            model_id=model_id,
            response_text=response_text,
            auto_input_generator=auto_input_generator,
            max_tool_calls=max_tool_calls,
            **kwargs
        )
        self.auto_terminate = auto_terminate
        self.preferred_tool = preferred_tool
        self.processed_tools = set()
        self.last_tool_result = None
    
    def reset(self) -> None:
        """重置模型状态"""
        self.call_count = 0
        self.processed_tools = set()
        self.last_tool_result = None
    
    def _get_first_tool_info(self, tool_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        获取工具信息，优先使用preferred_tool
        
        Args:
            tool_config: 工具配置
            
        Returns:
            工具信息
        """
        if not tool_config or not tool_config.get("tools"):
            raise ValueError("Agent中没有注册任何工具，无法执行Mock工具调用")
        
        tools = tool_config["tools"]
        
        # 如果指定了优先工具，尝试查找
        if self.preferred_tool:
            for tool in tools:
                if tool["name"] == self.preferred_tool:
                    return {
                        "name": tool["name"],
                        "spec": tool.get("inputSchema", {}).get("json", {}),
                        "description": tool.get("description", "")
                    }
        
        # 默认使用第一个工具
        first_tool = tools[0]
        return {
            "name": first_tool["name"],
            "spec": first_tool.get("inputSchema", {}).get("json", {}),
            "description": first_tool.get("description", "")
        }
    
    async def stream(self, messages, tool_specs=None, system_prompt=None) -> Any:
        """
        流式处理请求 - 返回一个异步迭代器
        
        Args:
            messages: 消息历史
            tool_specs: 工具规范
            system_prompt: 系统提示
            
        Returns:
            异步迭代器，产生响应事件
        """
        # 构建请求对象
        request = {
            "messages": messages,
            "tool_specs": tool_specs,
            "system_prompt": system_prompt
        }
        
        # 提取消息
        messages = request.get("messages", [])
        
        # 增加调用计数
        self.call_count += 1
        
        # 自动终止逻辑
        if self.auto_terminate and self.call_count > 1:
            # 提取上一个工具结果
            last_tool_info = self._extract_last_tool_info(messages)
            last_tool_result = self._extract_last_tool_result(messages)
            
            # 检查是否应该终止
            if (last_tool_info and last_tool_info["name"] in self.processed_tools) or self.call_count > 1:
                # 保存最后一个工具结果
                self.last_tool_result = last_tool_result
                
                # 返回终止响应
                yield {
                    "messageStart": {"role": "assistant"}
                }
                
                yield {
                    "contentBlockStart": {
                        "start": {"type": "text"}
                    }
                }
                
                yield {
                    "contentBlockDelta": {
                        "delta": {"text": self.response_text}
                    }
                }
                
                yield {
                    "contentBlockStop": {}
                }
                
                yield {
                    "messageStop": {
                        "stopReason": "end_turn"
                    }
                }
                
                yield {
                    "metadata": {
                        "usage": {
                            "inputTokens": 10,
                            "outputTokens": 15,
                            "totalTokens": 25
                        },
                        "metrics": {
                            "latencyMs": 100
                        },
                        "last_tool_result": self.last_tool_result
                    }
                }
                return
        
        # 创建一个异步生成器包装器
        class AsyncIteratorWrapper:
            def __init__(self, sync_iterator, parent_model):
                self.sync_iterator = sync_iterator
                self.parent_model = parent_model
                
            def __aiter__(self):
                return self
                
            async def __anext__(self):
                try:
                    event = next(self.sync_iterator)
                    # 如果是工具调用，记录工具名称
                    if "contentBlockStart" in event and "start" in event["contentBlockStart"]:
                        start = event["contentBlockStart"]["start"]
                        if "toolUse" in start:
                            self.parent_model.processed_tools.add(start["toolUse"]["name"])
                    return event
                except StopIteration:
                    raise StopAsyncIteration
        
        # 使用父类的stream方法，并将其包装为异步迭代器
        sync_events = super(EnhancedAutoMockModel, self).stream(request)
        async_events = AsyncIteratorWrapper(sync_events, self)
        
        # 异步迭代并yield事件
        async for event in async_events:
            yield event
    
    def _extract_last_tool_info(self, messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        提取最后一个工具调用信息
        
        Args:
            messages: 消息历史
            
        Returns:
            工具信息
        """
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                for content_block in msg.get("content", []):
                    if isinstance(content_block, dict) and content_block.get("toolUse"):
                        tool_use = content_block.get("toolUse", {})
                        return {
                            "name": tool_use.get("name", ""),
                            "input": tool_use.get("input", {})
                        }
        return None
    
    def _extract_last_tool_result(self, messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        提取最后一个工具执行结果
        
        Args:
            messages: 消息历史
            
        Returns:
            工具结果
        """
        for msg in reversed(messages):
            if msg.get("role") == "user" and msg.get("content"):
                for content_block in msg.get("content", []):
                    if isinstance(content_block, dict) and content_block.get("toolResult"):
                        return content_block.get("toolResult", {})
        return None


class UtilityAgent(Agent):
    """
    专注于直接工具执行的智能代理，继承自Strands Agent
    
    特点：
    1. 直接执行第一个工具，无需LLM推理
    2. 智能参数生成
    3. 完全兼容Strands Agent生态系统
    4. 支持所有Agent特性：state、session、conversation管理
    """
    
    def __init__(
        self,
        tools: List[Callable],
        preferred_tool: Optional[str] = None,
        auto_terminate: bool = True,
        response_text: str = "正在执行工具...",
        **kwargs
    ):
        """
        初始化UtilityAgent
        
        Args:
            tools: 工具函数列表
            preferred_tool: 优先使用的工具名称
            auto_terminate: 是否自动终止工具调用循环
            response_text: 响应文本
            **kwargs: 传递给Agent的其他参数
        """
        # 创建专用的Mock模型
        utility_model = self._create_utility_model(
            preferred_tool=preferred_tool,
            auto_terminate=auto_terminate,
            response_text=response_text
        )
        
        # 移除可能冲突的model参数
        kwargs.pop('model', None)
        
        # 调用父类构造函数
        super().__init__(
            model=utility_model,
            tools=tools,
            **kwargs
        )
        
        # UtilityAgent特有属性
        self.preferred_tool = preferred_tool
        self.auto_terminate = auto_terminate
        self.response_text = response_text
    
    def _create_utility_model(self, preferred_tool, auto_terminate, response_text):
        """创建专用的工具执行模型"""
        return EnhancedAutoMockModel(
            preferred_tool=preferred_tool,
            auto_terminate=auto_terminate,
            response_text=response_text,
            auto_input_generator=create_smart_input_generator(),
            max_tool_calls=2
        )
    
    def __call__(self, prompt, **kwargs):
        """重写调用方法，统一输出格式"""
        result = super().__call__(prompt, **kwargs)
        
        # 统一输出格式，将工具结果嵌入到消息内容中
        return self._unify_output_format(result)
    
    async def invoke_async(self, prompt, **kwargs):
        """异步调用方法"""
        result = await super().invoke_async(prompt, **kwargs)
        return self._unify_output_format(result)
    
    def _unify_output_format(self, result):
        """统一输出格式，使UtilityAgent的输出与标准Agent一致"""
        # 提取工具调用结果
        tool_result_text = self.last_tool_result
        
        if tool_result_text and hasattr(result, 'message'):
            # 修改消息内容，将工具结果作为主要内容
            if hasattr(result.message, 'content') and result.message.content:
                # 更新第一个content block的text为工具结果
                if isinstance(result.message.content, list) and len(result.message.content) > 0:
                    if isinstance(result.message.content[0], dict) and 'text' in result.message.content[0]:
                        result.message.content[0]['text'] = tool_result_text
                    else:
                        # 如果格式不符合预期，创建新的content结构
                        result.message.content = [{'text': tool_result_text}]
                else:
                    # 如果没有content，创建新的
                    result.message.content = [{'text': tool_result_text}]
            elif isinstance(result.message, dict):
                # 处理字典格式的message
                if 'content' in result.message:
                    if isinstance(result.message['content'], list) and len(result.message['content']) > 0:
                        if isinstance(result.message['content'][0], dict):
                            result.message['content'][0]['text'] = tool_result_text
                        else:
                            result.message['content'] = [{'text': tool_result_text}]
                    else:
                        result.message['content'] = [{'text': tool_result_text}]
                else:
                    result.message['content'] = [{'text': tool_result_text}]
        
        # 保留原有的增强信息
        if hasattr(result, '__dict__'):
            result.tool_results = self._extract_tool_results()
            result.utility_agent_info = {
                'preferred_tool': self.preferred_tool,
                'auto_terminate': self.auto_terminate,
                'response_text': self.response_text,
                'unified_output': True
            }
        
        return result
    
    def _extract_tool_results(self) -> Dict[str, Any]:
        """从消息历史中提取工具执行结果"""
        tool_results = {}
        
        if hasattr(self, 'messages'):
            for msg in reversed(self.messages):
                if isinstance(msg, dict) and msg.get('role') == 'user':
                    content = msg.get('content', [])
                    for block in content:
                        if isinstance(block, dict) and 'toolResult' in block:
                            tool_result = block['toolResult']
                            tool_use_id = tool_result.get('toolUseId', 'unknown')
                            
                            # 提取工具结果内容
                            if 'content' in tool_result:
                                for content_item in tool_result['content']:
                                    if isinstance(content_item, dict) and 'text' in content_item:
                                        tool_results[tool_use_id] = {
                                            'result': content_item['text'],
                                            'status': tool_result.get('status', 'success')
                                        }
        
        return tool_results
    
    def reset_model(self):
        """重置模型状态"""
        if hasattr(self.model, 'reset'):
            self.model.reset()
    
    def get_tool_result_text(self, tool_name: str) -> Optional[str]:
        """获取指定工具的执行结果文本"""
        tool_results = self._extract_tool_results()
        for tool_id, result_info in tool_results.items():
            if tool_name in tool_id or tool_name in result_info.get('result', ''):
                return result_info.get('result')
        return None
    
    def get_all_tool_results(self) -> Dict[str, str]:
        """获取所有工具的执行结果"""
        tool_results = self._extract_tool_results()
        simplified_results = {}
        
        for tool_id, result_info in tool_results.items():
            # 尝试从工具结果中提取工具名称
            result_text = result_info.get('result', '')
            if result_text:
                # 简化的工具名称提取逻辑
                if 'calculator' in tool_id.lower() or '计算' in result_text:
                    simplified_results['calculator'] = result_text
                elif 'weather' in tool_id.lower() or '天气' in result_text:
                    simplified_results['weather_query'] = result_text
                elif 'state' in tool_id.lower() or '状态' in result_text:
                    simplified_results['state_recorder'] = result_text
                elif 'counter' in tool_id.lower() or '计数' in result_text:
                    simplified_results['counter'] = result_text
                else:
                    simplified_results[tool_id] = result_text
        
        return simplified_results
    
    @property
    def last_tool_result(self) -> Optional[str]:
        """获取最后一个工具的执行结果"""
        tool_results = self.get_all_tool_results()
        if tool_results:
            return list(tool_results.values())[-1]
        return None
    
    def __repr__(self) -> str:
        """字符串表示"""
        return (f"UtilityAgent(name='{self.name}', "
                f"preferred_tool='{self.preferred_tool}', "
                f"tools={len(self.tool_names)}, "
                f"auto_terminate={self.auto_terminate})")


# 使用示例和工厂函数
def create_utility_agent(
    tools: List[Callable],
    name: str = "UtilityAgent",
    preferred_tool: Optional[str] = None,
    auto_terminate: bool = True,
    response_text: str = "正在执行工具...",
    session_manager: Optional[SessionManager] = None,
    state: Optional[Union[AgentState, dict]] = None,
    **kwargs
) -> UtilityAgent:
    """
    创建UtilityAgent的工厂函数
    
    Args:
        tools: 工具函数列表
        name: 代理名称
        preferred_tool: 优先使用的工具名称
        auto_terminate: 是否自动终止工具调用循环
        response_text: 响应文本
        session_manager: 会话管理器
        state: 初始状态
        **kwargs: 其他参数
        
    Returns:
        配置好的UtilityAgent实例
    """
    return UtilityAgent(
        tools=tools,
        name=name,
        preferred_tool=preferred_tool,
        auto_terminate=auto_terminate,
        response_text=response_text,
        session_manager=session_manager,
        state=state,
        **kwargs
    )


if __name__ == "__main__":
    # 简单的使用示例
    from strands import tool
    
    @tool
    def example_calculator(expression: str) -> str:
        """示例计算器工具"""
        try:
            result = eval(expression)
            return f"计算结果：{expression} = {result}"
        except Exception as e:
            return f"计算错误：{str(e)}"
    
    # 创建UtilityAgent
    agent = create_utility_agent(
        tools=[example_calculator],
        name="ExampleUtilityAgent",
        preferred_tool="example_calculator"
    )
    
    # 测试调用
    result = agent("计算 10 + 5")
    print(f"调用结果: {result}")
    print(f"工具结果: {agent.last_tool_result}")
    print(f"代理信息: {agent}")
