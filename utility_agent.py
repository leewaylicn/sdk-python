"""
UtilityAgent - 专注于工具函数执行的智能代理

将AutoMockToolCallingModel和Agent封装为一个统一的实用工具代理，
专门用于执行工具函数，支持工作流集成。
"""

from typing import List, Dict, Any, Optional, Callable, Union
import json
import random
from strands import Agent, tool
from strands.models.model import Model
from auto_mock_model import AutoMockToolCallingModel, create_smart_input_generator

class UtilityAgent:
    """
    专注于工具函数执行的智能代理
    
    特点：
    1. 自动选择或指定工具函数
    2. 智能生成参数
    3. 自动终止循环
    4. 简化的接口
    5. 支持工作流集成
    """
    
    def __init__(
        self,
        tools: List[Callable],
        name: str = "utility_agent",
        description: str = "执行工具函数的实用代理",
        response_text: str = "正在处理您的请求...",
        auto_input_generator: Optional[Callable] = None,
        preferred_tool: Optional[str] = None,
        auto_terminate: bool = True,
        **kwargs
    ):
        """
        初始化UtilityAgent
        
        Args:
            tools: 工具函数列表
            name: 代理名称
            description: 代理描述
            response_text: 响应文本
            auto_input_generator: 自定义输入生成器
            preferred_tool: 优先使用的工具名称（如果为None，则使用第一个工具）
            auto_terminate: 是否自动终止工具调用循环
            **kwargs: 传递给Agent的其他参数
        """
        self.name = name
        self.description = description
        self.tools = tools
        self.preferred_tool = preferred_tool
        
        # 创建智能输入生成器（如果未提供）
        if auto_input_generator is None:
            auto_input_generator = create_smart_input_generator()
        
        # 创建增强版的AutoMockToolCallingModel
        self.model = EnhancedAutoMockModel(
            response_text=response_text,  # 恢复响应文本，但确保工具结果被包含
            auto_input_generator=auto_input_generator,
            auto_terminate=True,  # 启用自动终止，在工具执行后停止
            preferred_tool=preferred_tool,
            max_tool_calls=2  # 允许多次工具调用
        )
        
        # 创建Agent
        self.agent = Agent(
            model=self.model,
            tools=tools,
            name=name,
            description=description,
            **kwargs
        )
    
    def __call__(self, input_text: str) -> Any:
        """
        执行代理，处理输入文本
        
        Args:
            input_text: 输入文本
            
        Returns:
            处理结果，包含工具调用结果
        """
        result = self.agent(input_text)
        
        # 提取工具调用结果并添加到结果中
        if hasattr(result, 'metrics') and hasattr(result.metrics, 'tool_metrics'):
            tool_results = {}
            for tool_name, tool_metrics in result.metrics.tool_metrics.items():
                if tool_metrics.success_count > 0:
                    # 从消息历史中提取工具结果
                    tool_result = self._extract_tool_result(tool_name)
                    if tool_result:
                        tool_results[tool_name] = tool_result
            
            # 将工具结果添加到AgentResult中
            if hasattr(result, '__dict__'):
                result.tool_results = tool_results
        
        return result
    
    def _extract_tool_result(self, tool_name: str) -> Optional[str]:
        """从消息历史中提取指定工具的结果"""
        if hasattr(self.agent, 'messages'):
            for msg in reversed(self.agent.messages):
                if isinstance(msg, dict) and msg.get('role') == 'user':
                    content = msg.get('content', [])
                    for block in content:
                        if isinstance(block, dict) and 'toolResult' in block:
                            tool_result = block['toolResult']
                            if 'content' in tool_result:
                                for content_item in tool_result['content']:
                                    if isinstance(content_item, dict) and 'text' in content_item:
                                        return content_item['text']
        return None
    
    async def invoke_async(self, input_text: str) -> Any:
        """
        异步执行代理，处理输入文本
        
        Args:
            input_text: 输入文本
            
        Returns:
            处理结果
        """
        return await self.agent.invoke_async(input_text)
    
    def get_tool_names(self) -> List[str]:
        """获取所有工具名称"""
        return self.agent.tool_names
    
    def reset(self) -> None:
        """重置代理状态"""
        if hasattr(self.model, 'reset'):
            self.model.reset()
    
    @property
    def state(self) -> Dict[str, Any]:
        """获取代理状态"""
        return self.agent.state.to_dict() if hasattr(self.agent, 'state') else {}
    
    @state.setter
    def state(self, value: Dict[str, Any]) -> None:
        """设置代理状态"""
        if hasattr(self.agent, 'state'):
            self.agent.state.from_dict(value)
    
    def get_tool_result_json(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """获取工具结果的JSON格式"""
        tool_result_str = self._extract_tool_result(tool_name)
        if tool_result_str:
            try:
                return json.loads(tool_result_str)
            except:
                return None
        return None
    
    # 为了与Strands Graph兼容，添加Agent的属性代理
    def __getattr__(self, name):
        """代理Agent的属性和方法"""
        if hasattr(self.agent, name):
            return getattr(self.agent, name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")


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
            **kwargs: 其他参数
        """
        super().__init__(
            model_id=model_id,
            response_text=response_text,
            auto_input_generator=auto_input_generator,
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


# 不再需要工厂函数，直接使用UtilityAgent类创建实例