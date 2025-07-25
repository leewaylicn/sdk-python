"""
智能输入生成器 - 基于工具规范自动推断参数

这个模块提供了一个完全自动化的输入生成系统，能够：
1. 分析工具的JSON Schema规范
2. 从用户输入中提取相关信息
3. 基于字段名称和描述进行语义匹配
4. 支持多种数据类型和复杂结构
5. 完全可扩展，无需硬编码
"""

import re
import json
from typing import Dict, Any, List, Optional, Union, Callable
from datetime import datetime
import random


class SmartInputGenerator:
    """
    智能输入生成器
    
    基于工具的JSON Schema规范和用户输入，自动生成合适的工具参数
    """
    
    def __init__(self):
        """初始化智能输入生成器"""
        # 语义映射规则 - 基于字段名称和描述的关键词匹配
        self.semantic_rules = {
            # 数学计算相关
            'math': {
                'keywords': ['expression', 'formula', 'equation', 'calculation', 'math', 'calculate', 'compute'],
                'extractors': [self._extract_math_expression]
            },
            
            # 地理位置相关
            'location': {
                'keywords': ['city', 'location', 'place', 'address', 'region', 'country', 'area'],
                'extractors': [self._extract_location]
            },
            
            # 时间相关
            'time': {
                'keywords': ['time', 'date', 'datetime', 'timestamp', 'when', 'schedule'],
                'extractors': [self._extract_time]
            },
            
            # 文本内容相关
            'text': {
                'keywords': ['text', 'content', 'message', 'body', 'description', 'note', 'comment'],
                'extractors': [self._extract_text_content]
            },
            
            # 邮件相关
            'email': {
                'keywords': ['email', 'mail', 'recipient', 'sender', 'to', 'from', 'subject'],
                'extractors': [self._extract_email_info]
            },
            
            # 数值相关
            'number': {
                'keywords': ['number', 'count', 'amount', 'quantity', 'size', 'length', 'width', 'height'],
                'extractors': [self._extract_numbers]
            },
            
            # 文件相关
            'file': {
                'keywords': ['file', 'filename', 'path', 'document', 'attachment'],
                'extractors': [self._extract_file_info]
            },
            
            # URL相关
            'url': {
                'keywords': ['url', 'link', 'website', 'uri', 'endpoint'],
                'extractors': [self._extract_url]
            }
        }
        
        # 常见地名数据库（可扩展）
        self.location_database = {
            'chinese_cities': ['北京', '上海', '广州', '深圳', '杭州', '南京', '武汉', '成都', '西安', '重庆'],
            'english_cities': ['Beijing', 'Shanghai', 'Guangzhou', 'Shenzhen', 'New York', 'London', 'Tokyo'],
            'countries': ['中国', '美国', '英国', '日本', '德国', 'China', 'USA', 'UK', 'Japan', 'Germany']
        }
    
    def generate_input(self, tool_info: Dict[str, Any], user_input: str) -> Dict[str, Any]:
        """
        基于工具信息和用户输入生成智能参数
        
        Args:
            tool_info: 工具信息，包含JSON Schema规范
            user_input: 用户输入文本
            
        Returns:
            生成的工具参数字典
        """
        tool_spec = tool_info.get("spec", {})
        properties = tool_spec.get("properties", {})
        required_fields = tool_spec.get("required", [])
        
        generated_params = {}
        
        # 遍历所有字段，智能生成参数
        for field_name, field_schema in properties.items():
            value = self._generate_field_value(
                field_name=field_name,
                field_schema=field_schema,
                user_input=user_input,
                is_required=field_name in required_fields
            )
            
            if value is not None:
                generated_params[field_name] = value
        
        return generated_params
    
    def _generate_field_value(self, field_name: str, field_schema: Dict[str, Any], 
                            user_input: str, is_required: bool = False) -> Any:
        """
        为单个字段生成值
        
        Args:
            field_name: 字段名称
            field_schema: 字段的JSON Schema
            user_input: 用户输入
            is_required: 是否为必需字段
            
        Returns:
            生成的字段值
        """
        field_type = field_schema.get("type", "string")
        field_description = field_schema.get("description", "")
        
        # 1. 尝试基于语义规则匹配
        semantic_value = self._extract_by_semantics(field_name, field_description, user_input)
        if semantic_value is not None:
            return self._convert_to_type(semantic_value, field_type, field_schema)
        
        # 2. 基于字段类型生成默认值
        return self._generate_default_value(field_type, field_schema, field_name, user_input)
    
    def _extract_by_semantics(self, field_name: str, field_description: str, user_input: str) -> Any:
        """
        基于语义规则提取值
        
        Args:
            field_name: 字段名称
            field_description: 字段描述
            user_input: 用户输入
            
        Returns:
            提取的值或None
        """
        # 组合字段名称和描述进行匹配
        search_text = f"{field_name} {field_description}".lower()
        
        # 遍历语义规则
        for category, rule in self.semantic_rules.items():
            # 检查关键词匹配
            if any(keyword in search_text for keyword in rule['keywords']):
                # 尝试所有提取器
                for extractor in rule['extractors']:
                    result = extractor(user_input)
                    if result is not None:
                        return result
        
        return None
    
    def _extract_math_expression(self, text: str) -> Optional[str]:
        """提取数学表达式"""
        # 匹配数学表达式模式
        patterns = [
            r'[\d+\-*/\(\)\s\.]+',  # 基本数学表达式
            r'\d+\s*[+\-*/]\s*\d+',  # 简单运算
            r'\d+(\.\d+)?',  # 单个数字
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text)
            if matches:
                # 返回最长的匹配
                return max(matches, key=len).strip()
        
        return None
    
    def _extract_location(self, text: str) -> Optional[str]:
        """提取地理位置"""
        # 检查所有地名数据库
        for category, locations in self.location_database.items():
            for location in locations:
                if location in text:
                    return location
        
        # 尝试提取可能的地名（中文地名通常以"市"、"省"、"区"结尾）
        chinese_location_pattern = r'[\u4e00-\u9fff]+[市省区县]'
        matches = re.findall(chinese_location_pattern, text)
        if matches:
            return matches[0]
        
        return None
    
    def _extract_time(self, text: str) -> Optional[str]:
        """提取时间信息"""
        # 时间模式匹配
        time_patterns = [
            r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
            r'\d{2}:\d{2}',  # HH:MM
            r'\d{4}年\d{1,2}月\d{1,2}日',  # 中文日期
            r'今天|明天|昨天',  # 相对时间
        ]
        
        for pattern in time_patterns:
            matches = re.findall(pattern, text)
            if matches:
                return matches[0]
        
        # 如果没有找到具体时间，返回当前时间
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def _extract_text_content(self, text: str) -> Optional[str]:
        """提取文本内容"""
        # 对于文本字段，通常返回用户输入本身或其摘要
        if len(text) > 100:
            # 如果文本太长，返回前100个字符
            return text[:100] + "..."
        return text
    
    def _extract_email_info(self, text: str) -> Optional[str]:
        """提取邮件信息"""
        # 邮件地址模式
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        matches = re.findall(email_pattern, text)
        if matches:
            return matches[0]
        
        # 如果没有找到邮件地址，返回默认值
        return "user@example.com"
    
    def _extract_numbers(self, text: str) -> Optional[Union[int, float]]:
        """提取数字"""
        # 提取所有数字
        numbers = re.findall(r'\d+\.?\d*', text)
        if numbers:
            # 返回第一个数字，尝试转换为适当类型
            num_str = numbers[0]
            if '.' in num_str:
                return float(num_str)
            else:
                return int(num_str)
        
        return None
    
    def _extract_file_info(self, text: str) -> Optional[str]:
        """提取文件信息"""
        # 文件路径或文件名模式
        file_patterns = [
            r'[^\s]+\.[a-zA-Z0-9]+',  # 带扩展名的文件
            r'/[^\s]+',  # Unix路径
            r'[A-Z]:\\[^\s]+',  # Windows路径
        ]
        
        for pattern in file_patterns:
            matches = re.findall(pattern, text)
            if matches:
                return matches[0]
        
        return None
    
    def _extract_url(self, text: str) -> Optional[str]:
        """提取URL"""
        url_pattern = r'https?://[^\s]+'
        matches = re.findall(url_pattern, text)
        if matches:
            return matches[0]
        
        return None
    
    def _convert_to_type(self, value: Any, target_type: str, field_schema: Dict[str, Any]) -> Any:
        """
        将值转换为目标类型
        
        Args:
            value: 原始值
            target_type: 目标类型
            field_schema: 字段schema
            
        Returns:
            转换后的值
        """
        try:
            if target_type == "string":
                return str(value)
            elif target_type == "integer":
                if isinstance(value, str):
                    # 从字符串中提取数字
                    numbers = re.findall(r'\d+', value)
                    return int(numbers[0]) if numbers else 0
                return int(value)
            elif target_type == "number":
                if isinstance(value, str):
                    numbers = re.findall(r'\d+\.?\d*', value)
                    return float(numbers[0]) if numbers else 0.0
                return float(value)
            elif target_type == "boolean":
                if isinstance(value, str):
                    return value.lower() in ['true', '是', 'yes', '1']
                return bool(value)
            elif target_type == "array":
                if isinstance(value, str):
                    # 尝试分割字符串
                    return [item.strip() for item in value.split(',')]
                return [value] if not isinstance(value, list) else value
            else:
                return value
        except (ValueError, TypeError):
            return value
    
    def _generate_default_value(self, field_type: str, field_schema: Dict[str, Any], 
                              field_name: str, user_input: str) -> Any:
        """
        生成默认值
        
        Args:
            field_type: 字段类型
            field_schema: 字段schema
            field_name: 字段名称
            user_input: 用户输入
            
        Returns:
            默认值
        """
        # 检查是否有默认值
        if "default" in field_schema:
            return field_schema["default"]
        
        # 检查是否有枚举值
        if "enum" in field_schema:
            return field_schema["enum"][0]
        
        # 基于类型生成默认值
        if field_type == "string":
            return user_input if user_input else f"auto_{field_name}"
        elif field_type == "integer":
            return random.randint(1, 100)
        elif field_type == "number":
            return round(random.uniform(1.0, 100.0), 2)
        elif field_type == "boolean":
            return True
        elif field_type == "array":
            return [f"item_{i}" for i in range(1, 3)]
        elif field_type == "object":
            return {"key": "value"}
        else:
            return None


def create_smart_input_generator() -> Callable:
    """
    创建智能输入生成器实例
    
    Returns:
        智能输入生成函数
    """
    generator = SmartInputGenerator()
    
    def smart_input_generator(tool_info: Dict[str, Any], messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        智能输入生成器函数
        
        Args:
            tool_info: 工具信息
            messages: 消息历史
            
        Returns:
            生成的工具输入参数
        """
        # 提取最后一条用户消息
        user_input = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
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


# 使用示例和测试
if __name__ == "__main__":
    # 创建智能生成器
    generator = SmartInputGenerator()
    
    # 测试用例
    test_cases = [
        {
            "tool_info": {
                "name": "calculator",
                "spec": {
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "Mathematical expression to calculate"
                        }
                    },
                    "required": ["expression"]
                }
            },
            "user_input": "请计算 15 * 8 + 5"
        },
        {
            "tool_info": {
                "name": "weather_check",
                "spec": {
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "City name to check weather"
                        },
                        "date": {
                            "type": "string",
                            "description": "Date for weather check"
                        }
                    },
                    "required": ["city"]
                }
            },
            "user_input": "今天北京的天气怎么样？"
        },
        {
            "tool_info": {
                "name": "send_email",
                "spec": {
                    "properties": {
                        "to": {
                            "type": "string",
                            "description": "Recipient email address"
                        },
                        "subject": {
                            "type": "string",
                            "description": "Email subject"
                        },
                        "body": {
                            "type": "string",
                            "description": "Email body content"
                        }
                    },
                    "required": ["to", "subject", "body"]
                }
            },
            "user_input": "发送邮件给 john@example.com，主题是会议通知"
        }
    ]
    
    print("智能输入生成器测试")
    print("=" * 50)
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n测试用例 {i}:")
        print(f"工具: {test_case['tool_info']['name']}")
        print(f"用户输入: {test_case['user_input']}")
        
        result = generator.generate_input(test_case['tool_info'], test_case['user_input'])
        print(f"生成参数: {json.dumps(result, ensure_ascii=False, indent=2)}")
