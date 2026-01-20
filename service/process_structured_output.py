"""
结构化输出处理模块

用于处理模型返回的结构化输出,提取并验证各个字段。

输入格式示例:
{
    "output": {
        "think_output": "...",
        "text": "...",
        "image_info": [...],
        "timer": 60,
        "scheduled_events": "...",
        "leap_events": "..."
    }
}

或兼容 output 为 JSON 字符串的格式:
{
    "output": "{\\"think_output\\": \\"...\\", \\"text\\": \\"...\\"}"
}
"""

import json
from typing import Any, Dict, List, Optional, Tuple


# 各字段的空值默认值
EMPTY_VALUES = {
    "text": "",
    "think_output": "",
    "image_info": [],
    "timer": None,
    "scheduled_events": "",
    "leap_events": "",
}


# 结构化输出的字段定义
FIELD_DEFINITIONS = {
    "text": {
        "type": str,
        "required": True,
        "description": "你的回复内容",
    },
    "think_output": {
        "type": str,
        "required": True,
        "description": "你的思考过程",
    },
    "image_info": {
        "type": list,
        "required": False,
        "description": "针对用户上传的图片内容进行描述",
    },
    "timer": {
        "type": (int, float),
        "required": False,
        "description": "定时任务的相对时间(分钟数)",
    },
    "scheduled_events": {
        "type": str,
        "required": False,
        "description": "不会因用户在计划执行前对话而失效的定时任务内容",
    },
    "leap_events": {
        "type": str,
        "required": False,
        "description": "会因用户在计划执行前对话而失效的定时任务内容",
    },
}


class ValidationError:
    """字段验证错误"""

    def __init__(self, field: str, message: str, value: Any = None):
        self.field = field
        self.message = message
        self.value = value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field,
            "message": self.message,
            "value": self.value,
        }


class ValidationResult:
    """验证结果"""

    def __init__(self):
        self.is_valid = True
        self.errors: List[ValidationError] = []
        self.warnings: List[Dict[str, str]] = []

    def add_error(self, field: str, message: str, value: Any = None) -> None:
        self.is_valid = False
        self.errors.append(ValidationError(field, message, value))

    def add_warning(self, field: str, message: str) -> None:
        self.warnings.append({"field": field, "message": message})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": self.warnings,
        }


def _validate_type(value: Any, expected_type: tuple, field_name: str) -> Tuple[bool, Optional[str]]:
    """验证值的类型是否匹配预期类型

    Args:
        value: 待验证的值
        expected_type: 预期类型(可能为元组,支持多种类型)
        field_name: 字段名称(用于错误信息)

    Returns:
        (is_valid, error_message)
    """
    if value is None:
        return True, None  # None值由required检查处理

    if isinstance(expected_type, tuple):
        if not isinstance(value, expected_type):
            type_names = [t.__name__ for t in expected_type]
            return False, f"期望类型为 {', '.join(type_names)} 之一, 实际为 {type(value).__name__}"
    else:
        if not isinstance(value, expected_type):
            return False, f"期望类型为 {expected_type.__name__}, 实际为 {type(value).__name__}"

    return True, None


def _validate_timer_value(value: Any) -> Tuple[bool, Optional[str]]:
    """验证timer字段的值

    Args:
        value: timer值

    Returns:
        (is_valid, error_message)
    """
    if value is None:
        return True, None

    if not isinstance(value, (int, float)):
        return False, f"timer必须是数字类型, 实际为 {type(value).__name__}"

    if value < 0:
        return False, f"timer必须为非负数, 实际为 {value}"

    return True, None


def _validate_image_info(value: Any) -> Tuple[bool, Optional[str]]:
    """验证image_info字段的值

    Args:
        value: image_info值

    Returns:
        (is_valid, error_message)
    """
    if value is None:
        return True, None

    if not isinstance(value, list):
        return False, f"image_info必须是数组类型, 实际为 {type(value).__name__}"

    for idx, item in enumerate(value):
        if not isinstance(item, str):
            return False, f"image_info[{idx}]必须是字符串类型, 实际为 {type(item).__name__}"

    return True, None


def _normalize_field_key(key: str, known_fields: set) -> str:
    """归一化字段键名，处理 LLM 可能返回的各种格式变体

    支持的变体:
    - "text" -> "text" (标准格式)
    - ":text" -> "text" (冒号前缀)
    - "::text" -> "text" (双冒号前缀)
    - "field:text" -> "text" (包含目标字段名)

    Args:
        key: 原始键名
        known_fields: 已知字段名集合

    Returns:
        归一化后的键名，如果无法识别则返回原键名
    """
    # 如果键名直接匹配已知字段，直接返回
    if key in known_fields:
        return key

    # 检查键名中是否包含已知字段名
    for field in known_fields:
        if field in key:
            return field

    # 无法识别，返回原键名
    return key


def _normalize_dict_keys(data: Dict[str, Any], known_fields: set) -> Dict[str, Any]:
    """归一化字典中的所有键名

    Args:
        data: 原始字典
        known_fields: 已知字段名集合

    Returns:
        键名归一化后的字典
    """
    normalized = {}
    for key, value in data.items():
        normalized_key = _normalize_field_key(key, known_fields)
        normalized[normalized_key] = value
    return normalized


def extract_structured_output(input_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从输入数据中提取结构化输出

    支持两种格式:
    1. output 为字典对象: {"output": {"text": "...", ...}}
    2. output 为 JSON 字符串: {"output": "{\\"text\\": \\"...\\"}"}

    同时处理 LLM 可能返回的键名格式变体，如 ":text" -> "text"

    Args:
        input_data: 输入的字典数据

    Returns:
        提取到的结构化输出字典, 如果输入格式错误则返回None
    """
    if not isinstance(input_data, dict):
        return None

    output = input_data.get("output")
    if output is None:
        return None

    # 格式1: output 已经是字典
    if isinstance(output, dict):
        # 归一化键名（处理 :text -> text 等情况）
        known_fields = set(FIELD_DEFINITIONS.keys())
        return _normalize_dict_keys(output, known_fields)

    # 格式2: output 是 JSON 字符串，需要解析
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
            if isinstance(parsed, dict):
                # 归一化键名（处理 :text -> text 等情况）
                known_fields = set(FIELD_DEFINITIONS.keys())
                return _normalize_dict_keys(parsed, known_fields)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    return None


def _get_empty_result() -> Dict[str, Any]:
    """获取全空值的结果字典

    Returns:
        包含所有字段空值的字典
    """
    return EMPTY_VALUES.copy()


def validate_field(field_name: str, value: Any, result: ValidationResult) -> Any:
    """验证单个字段

    Args:
        field_name: 字段名称
        value: 字段值
        result: 验证结果对象

    Returns:
        处理后的值(可能进行类型转换)
    """
    if field_name not in FIELD_DEFINITIONS:
        result.add_warning(field_name, f"未知字段 '{field_name}'")
        return value

    definition = FIELD_DEFINITIONS[field_name]

    # 检查必填字段
    if definition["required"] and value is None:
        result.add_error(field_name, f"必填字段 '{field_name}' 缺失")
        return EMPTY_VALUES.get(field_name, "")

    # 值为None且非必填时跳过类型检查
    if value is None and not definition["required"]:
        return EMPTY_VALUES.get(field_name, "")

    # 特殊字段验证
    if field_name == "timer":
        is_valid, error_msg = _validate_timer_value(value)
        if not is_valid:
            result.add_error(field_name, error_msg, value)
            return EMPTY_VALUES.get(field_name, "")

    if field_name == "image_info":
        is_valid, error_msg = _validate_image_info(value)
        if not is_valid:
            result.add_error(field_name, error_msg, value)
            return EMPTY_VALUES.get(field_name, "")

    # 通用类型验证
    expected_type = definition["type"]
    is_valid, error_msg = _validate_type(value, expected_type, field_name)
    if not is_valid:
        result.add_error(field_name, error_msg, value)
        return EMPTY_VALUES.get(field_name, "")

    return value


def process_structured_output(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """处理结构化输出,提取并验证所有字段

    Args:
        input_data: 输入的字典数据,格式为: {"output": {...}}

    Returns:
        展平的结果字典,包含所有字段:
        - text: str, 回复内容
        - think_output: str, 思考过程
        - image_info: list, 图片描述列表
        - timer: float/None, 定时器分钟数
        - scheduled_events: str, 持久化定时任务
        - leap_events: str, 临时定时任务
        - is_valid: bool, 验证是否通过
        - validation_errors: list, 验证错误列表
        - validation_warnings: list, 验证警告列表
    """
    result = ValidationResult()

    # 初始化结果为空值字典
    processed_data = _get_empty_result()

    # 提取结构化输出
    output = extract_structured_output(input_data)

    if output is None:
        result.add_error("structured_output", "输入格式错误,无法找到 structured_output.output")
    else:
        # 处理每个字段
        for field_name in FIELD_DEFINITIONS.keys():
            value = output.get(field_name)
            processed_value = validate_field(field_name, value, result)
            processed_data[field_name] = processed_value

        # 检查是否有额外的未知字段
        for field_name in output.keys():
            if field_name not in FIELD_DEFINITIONS:
                result.add_warning(field_name, f"未知字段 '{field_name}'")

    # 返回展平的完整字典
    return {
        "text": processed_data.get("text", ""),
        "think_output": processed_data.get("think_output", ""),
        "image_info": processed_data.get("image_info", []),
        "timer": processed_data.get("timer"),
        "scheduled_events": processed_data.get("scheduled_events", ""),
        "leap_events": processed_data.get("leap_events", ""),
        "is_valid": result.is_valid,
        "validation_errors": [e.to_dict() for e in result.errors],
        "validation_warnings": result.warnings,
    }


def get_text_response(processed: Dict[str, Any]) -> str:
    """从处理后的数据中获取text回复内容

    Args:
        processed: process_structured_output返回的字典

    Returns:
        text字段的值
    """
    if isinstance(processed, dict):
        return processed.get("text", "")
    return ""


def get_think_output(processed: Dict[str, Any]) -> str:
    """从处理后的数据中获取think_output思考内容

    Args:
        processed: process_structured_output返回的字典

    Returns:
        think_output字段的值
    """
    if isinstance(processed, dict):
        return processed.get("think_output", "")
    return ""


def get_timer_info(processed: Dict[str, Any]) -> Optional[float]:
    """从处理后的数据中获取timer定时任务信息

    Args:
        processed: process_structured_output返回的字典

    Returns:
        timer字段的值(分钟数)
    """
    if isinstance(processed, dict):
        return processed.get("timer")
    return None


def has_scheduled_events(processed: Dict[str, Any]) -> bool:
    """检查是否有持久化定时任务

    Args:
        processed: process_structured_output返回的字典

    Returns:
        是否包含scheduled_events
    """
    if isinstance(processed, dict):
        return bool(processed.get("scheduled_events"))
    return False


def has_leap_events(processed: Dict[str, Any]) -> bool:
    """检查是否有临时定时任务

    Args:
        processed: process_structured_output返回的字典

    Returns:
        是否包含leap_events
    """
    if isinstance(processed, dict):
        return bool(processed.get("leap_events"))
    return False


def get_image_descriptions(processed: Dict[str, Any]) -> List[str]:
    """从处理后的数据中获取图片描述

    Args:
        processed: process_structured_output返回的字典

    Returns:
        image_info数组
    """
    if isinstance(processed, dict):
        image_info = processed.get("image_info")
        if isinstance(image_info, list):
            return image_info
    return []


def main(structured_output: Dict[str, Any]) -> Dict[str, Any]:
    """主入口函数,处理结构化输出

    Args:
        structured_output: 输入的字典数据, 格式: {"output": {...}}

    Returns:
        展平的结果字典,无论何种情况都包含所有字段:
        - text: str
        - think_output: str
        - image_info: list
        - timer: float/None
        - scheduled_events: str
        - leap_events: str
        - is_valid: bool
        - validation_errors: list
        - validation_warnings: list
    """
    # 默认空值结果
    text = ""
    think_output = ""
    image_info = []
    timer = None
    scheduled_events = ""
    leap_events = ""
    is_valid = False
    validation_errors = []
    validation_warnings = []

    try:
        result = ValidationResult()

        # 提取结构化输出
        output = extract_structured_output(structured_output)

        if output is not None:
            # 处理每个已知字段
            for field_name in FIELD_DEFINITIONS.keys():
                value = output.get(field_name)
                processed_value = validate_field(field_name, value, result)

                if field_name == "text":
                    text = processed_value
                elif field_name == "think_output":
                    think_output = processed_value
                elif field_name == "image_info":
                    image_info = processed_value
                elif field_name == "timer":
                    timer = processed_value
                elif field_name == "scheduled_events":
                    scheduled_events = processed_value
                elif field_name == "leap_events":
                    leap_events = processed_value

            # 检查是否有额外的未知字段
            for field_name in output.keys():
                if field_name not in FIELD_DEFINITIONS:
                    result.add_warning(field_name, f"未知字段 '{field_name}'")

        else:
            result.add_error("output", "输入格式错误,无法找到 output 字段")

        is_valid = result.is_valid
        validation_errors = [e.to_dict() for e in result.errors]
        validation_warnings = result.warnings

    except Exception:
        is_valid = False
        validation_errors = [{"field": "unknown", "message": "处理过程中发生异常", "value": None}]
        validation_warnings = []

    # 显式构建返回字典
    return {
        "text": text,  # type: str
        "think_output": think_output,  # type: str
        "image_info": image_info,  # type: list
        "timer": timer,  # type: float | None
        "scheduled_events": scheduled_events,  # type: str
        "leap_events": leap_events,  # type: str
        "is_valid": is_valid,  # type: bool
        "validation_errors": validation_errors,  # type: list
        "validation_warnings": validation_warnings,  # type: list
    }
