"""
AutoMockToolCallingModel - 自动选择Agent中第一个工具的Mock模型

这个模型实现了Model接口，能够自动选择Agent中注册的第一个工具进行调用，
并根据工具规范和用户输入智能生成参数。
"""

from typing import Iterator, Dict, Any, List, Optional, Callable
import uuid
import re
import json
from strands.models.model import Model
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolConfig, ToolSpec
from strands.types.content import Messages


class AutoMockToolCallingModel(Model):
    """
    自动选择Agent中第一个工具的Mock模型
    
    特点：
    1. 不需要预定义工具调用列表
    2. 自动使用Agent中注册的第一个工具
    3. 智能生成工具输入参数
    4. 没有工具时提供清晰的错误信息
    """
    
    def __init__(
        self,
        model_id: str = "auto-mock-tool-caller",
        response_text: str = "我将使用可用的工具来帮助您。",
        auto_input_generator: Optional[Callable] = None,
        max_tool_calls: int = 1,
        **kwargs
    ):
        """
        初始化自动Mock模型
        
        Args:
            model_id: 模型标识符
            response_text: 可选的响应文本
            auto_input_generator: 自定义输入生成函数
            max_tool_calls: 最大工具调用次数，防止无限递归
            **kwargs: 其他配置参数
        """
        self.model_id = model_id
        self.response_text = response_text
        self.auto_input_generator = auto_input_generator
        self.max_tool_calls = max_tool_calls
        self.call_count = 0  # 工具调用计数器
        self.config = {
            "model_id": model_id,
            "streaming": True,
            **kwargs
        }
    
    def _get_first_tool_info(self, tool_config: Optional[ToolConfig]) -> Dict[str, Any]:
        """
        从tool_config中获取第一个工具的信息
        
        Args:
            tool_config: 工具配置对象
            
        Returns:
            包含工具名称、规范和描述的字典
            
        Raises:
            ValueError: 当没有注册任何工具时
        """
        if not tool_config or not tool_config.get("tools"):
            raise ValueError("Agent中没有注册任何工具，无法执行Mock工具调用")
        
        first_tool = tool_config["tools"][0]
        tool_name = first_tool["name"]
        tool_spec = first_tool.get("inputSchema", {}).get("json", {})
        
        return {
            "name": tool_name,
            "spec": tool_spec,
            "description": first_tool.get("description", "")
        }
    
    def _generate_tool_input(self, tool_info: Dict[str, Any], messages: Messages) -> Dict[str, Any]:
        """
        根据工具规范自动生成输入参数
        
        Args:
            tool_info: 工具信息字典
            messages: 消息历史
            
        Returns:
            生成的工具输入参数字典
        """
        if self.auto_input_generator:
            return self.auto_input_generator(tool_info, messages)
        
        # 默认输入生成逻辑
        tool_spec = tool_info["spec"]
        properties = tool_spec.get("properties", {})
        required_fields = tool_spec.get("required", [])
        
        auto_input = {}
        
        # 从最后一条用户消息中提取可能的参数
        last_user_message = self._extract_last_user_message(messages)
        
        for field_name, field_info in properties.items():
            field_type = field_info.get("type", "string")
            
            if field_type == "string":
                if field_name in ["message", "text", "content", "query"]:
                    auto_input[field_name] = last_user_message
                elif field_name in ["expression", "formula"]:
                    # 尝试提取数学表达式
                    math_pattern = r'[\d+\-*/\(\)\s]+'
                    matches = re.findall(math_pattern, last_user_message)
                    auto_input[field_name] = matches[0].strip() if matches else "1+1"
                elif field_name in ["city", "location"]:
                    # 尝试提取城市名
                    cities = ["北京", "上海", "广州", "深圳", "杭州", "南京", "武汉", "成都"]
                    for city in cities:
                        if city in last_user_message:
                            auto_input[field_name] = city
                            break
                    else:
                        auto_input[field_name] = "北京"
                else:
                    auto_input[field_name] = f"auto_{field_name}"
            
            elif field_type == "number":
                # 尝试从消息中提取数字
                numbers = re.findall(r'\d+', last_user_message)
                auto_input[field_name] = int(numbers[0]) if numbers else 42
            
            elif field_type == "boolean":
                auto_input[field_name] = True
            
            elif field_type == "array":
                auto_input[field_name] = ["auto_item"]
            
            elif field_type == "object":
                auto_input[field_name] = {"auto_key": "auto_value"}
        
        # 确保必需字段都有值
        for required_field in required_fields:
            if required_field not in auto_input:
                auto_input[required_field] = "auto_required_value"
        
        return auto_input
    
    def _extract_last_user_message(self, messages: Messages) -> str:
        """
        提取最后一条用户消息
        
        Args:
            messages: 消息历史列表
            
        Returns:
            最后一条用户消息的文本内容
        """
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", [])
                for block in content:
                    if block.get("text"):
                        return block["text"]
        return "默认用户输入"
    
    def format_request(
        self, 
        messages: Messages, 
        tool_specs: Optional[List[ToolSpec]] = None, 
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        格式化请求 - Mock模型不需要实际格式化，直接返回原始数据
        
        Args:
            messages: 消息列表
            tool_specs: 工具规范列表
            system_prompt: 系统提示
            
        Returns:
            格式化的请求字典
        """
        return {
            "messages": messages,
            "tool_specs": tool_specs,
            "system_prompt": system_prompt
        }
    
    def stream(self, request: Any) -> Iterator[Any]:
        """
        发送请求到模型并获取流式响应
        
        Args:
            request: 格式化的请求
            
        Yields:
            模型响应事件
        """
        # 增加调用计数
        self.call_count += 1
        
        # 检查是否超过最大调用次数
        if self.call_count > self.max_tool_calls:
            yield {
                "messageStart": {"role": "assistant"}
            }
            
            yield {
                "contentBlockStart": {
                    "start": {"type": "text"}
                }
            }
            
            response_text = "根据工具执行结果，我已经为您完成了请求的操作。"
            if self.response_text:
                response_text = self.response_text
            
            yield {
                "contentBlockDelta": {
                    "delta": {"text": response_text}
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
                    }
                }
            }
            return
        
        # 从请求中提取数据
        messages = request.get("messages", [])
        tool_specs = request.get("tool_specs", [])
        system_prompt = request.get("system_prompt")
        
        # 构建tool_config
        tool_config = None
        if tool_specs:
            tool_config = {
                "tools": [
                    {
                        "name": spec["name"],
                        "description": spec.get("description", ""),
                        "inputSchema": spec.get("inputSchema", {})
                    }
                    for spec in tool_specs
                ]
            }
        
        # 调用原来的stream方法逻辑
        try:
            # 获取第一个工具信息
            tool_info = self._get_first_tool_info(tool_config)
            tool_name = tool_info["name"]
            
            # 生成工具输入
            tool_input = self._generate_tool_input(tool_info, messages)
            tool_use_id = f"auto_{tool_name}_{hash(str(tool_input)) % 10000}"
            
            # 开始消息事件
            yield {
                "messageStart": {
                    "role": "assistant"
                }
            }
            
            # 响应文本（可选）
            if self.response_text:
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
            
            # 工具调用事件
            yield {
                "contentBlockStart": {
                    "start": {
                        "type": "toolUse",
                        "toolUse": {
                            "toolUseId": tool_use_id,
                            "name": tool_name
                        }
                    }
                }
            }
            
            yield {
                "contentBlockDelta": {
                    "delta": {
                        "toolUse": {
                            "input": json.dumps(tool_input) if isinstance(tool_input, dict) else str(tool_input)
                        }
                    }
                }
            }
            
            yield {
                "contentBlockStop": {}
            }
            
            # 消息结束
            yield {
                "messageStop": {
                    "stopReason": "tool_use"
                }
            }
            
            # 元数据
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
                    "auto_selected_tool": tool_name,
                    "tool_input": tool_input
                }
            }
            
        except ValueError as e:
            # 没有工具时的错误处理
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
                    "delta": {"text": f"错误：{str(e)}"}
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
    
    def format_chunk(self, event: Dict[str, Any]) -> StreamEvent:
        """格式化响应块"""
        return event
    
    def update_config(self, **model_config) -> None:
        """更新模型配置"""
        self.config.update(model_config)
    
    def get_config(self) -> Dict[str, Any]:
        """获取模型配置"""
        return self.config.copy()
    
    async def structured_output(
        self,
        output_model,
        prompt: Messages,
        **kwargs
    ) -> Iterator[Dict[str, Any]]:
        """结构化输出（简单实现）"""
        yield {"output": None}


def create_smart_input_generator() -> Callable:
    """
    创建智能输入生成器
    
    使用新的基于语义分析的智能生成器，完全自动化，无硬编码
    
    Returns:
        智能输入生成函数
    """
    # 导入新的智能生成器
    from smart_input_generator import SmartInputGenerator
    
    generator = SmartInputGenerator()
    
    def smart_input_generator(tool_info: Dict[str, Any], messages: Messages) -> Dict[str, Any]:
        """
        智能输入生成器
        
        Args:
            tool_info: 工具信息
            messages: 消息历史
            
        Returns:
            生成的工具输入参数
        """
        # 提取最后一条用户消息
        user_input = ""
        for msg in reversed(messages):
            if hasattr(msg, 'role') and msg.role == "user":
                if hasattr(msg, 'content'):
                    content = msg.content
                    if isinstance(content, str):
                        user_input = content
                        break
                    elif isinstance(content, list):
                        for block in content:
                            if hasattr(block, 'text'):
                                user_input = block.text
                                break
                        if user_input:
                            break
            elif isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", [])
                if isinstance(content, str):
                    user_input = content
                    break
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("text"):
                            user_input = block["text"]
                            break
                    if user_input:
                        break
        
        # 使用智能生成器生成参数
        return generator.generate_input(tool_info, user_input)
    
    return smart_input_generator


# 使用示例
if __name__ == "__main__":
    print("AutoMockToolCallingModel 实现完成！")
    print("主要特点：")
    print("1. 自动选择Agent中的第一个工具")
    print("2. 智能生成工具输入参数")
    print("3. 支持自定义输入生成逻辑")
    print("4. 完整的错误处理机制")
