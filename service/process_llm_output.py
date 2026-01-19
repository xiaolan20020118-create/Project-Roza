import re
import random
from typing import Any


def random_message(messages: Any) -> str:
    """从消息数组中随机选择一条消息，如果不是数组则返回字符串本身"""
    if isinstance(messages, list):
        if not messages:
            return ""
        return random.choice(messages)
    return str(messages) if messages else ""

def main(llm_output: str, error_output: Any) -> dict:
    """
    处理LLM输出,移除思考内容和工具调用,只保留正常回复内容

    Args:
        llm_output: LLM的原始输出
        error_output: 当无法提取有效内容时的默认输出（可以是字符串或字符串数组）

    Returns:
        dict: 包含system_output和review_result的字典
    """
    
    # 处理LLM输出,移除思考和工具调用标签
    system_output = process_llm_response(llm_output, error_output)
    
    # 检查是否包含警告标记
    if "[warn]" in llm_output:
        review_result = "warn"
    else:
        review_result = "pass"
    
    return {
        "system_output": system_output,  # type: str
        "review_result": review_result  # type: str
    }


def process_llm_response(text: str, error_output: Any) -> str:
    """
    处理LLM响应,移除<think>和<tool_call>标签及其内容
    
    处理策略:
    1. 先匹配并删除所有成对的标签及其内容
    2. 若还有残留的</think>标签,则删除</think>及其后的所有内容
    3. 若还有残留的</tool_call>标签,则删除</tool_call>及其后的所有内容
    4. 检查输出是否为空,为空则返回error_output
    
    Args:
        text: 原始LLM输出
        error_output: 当无法提取有效内容时的默认输出（可以是字符串或字符串数组）

    Returns:
        str: 处理后的输出内容
    """
    if not text:
        return random_message(error_output)
    
    # 步骤1: 移除所有成对出现的<think>...</think>和<tool_call>...</tool_call>
    # 使用正则表达式,非贪婪匹配,处理多个标签对
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'<tool_call>.*?</tool_call>', '', text, flags=re.DOTALL)
    
    # 步骤2: 如果还有残留的</think>标签,删除</think>及其后的所有内容
    if '</think>' in text:
        think_end_pos = text.find('</think>')
        text = text[:think_end_pos]
    
    # 步骤3: 如果还有残留的</tool_call>标签,删除</tool_call>及其后的所有内容
    if '</tool_call>' in text:
        tool_call_end_pos = text.find('</tool_call>')
        text = text[:tool_call_end_pos]
    
    # 清理多余的空白字符和换行
    text = text.strip()
    
    # 步骤4: 检查输出是否为空,为空则返回error_output（随机选择如果error_output是数组）
    if not text or text.isspace():
        return random_message(error_output)
    
    return text


def handle_malformed_output(text: str) -> str:
    """
    处理格式异常的输出
    
    故障1: <think>思考</think>正常内容</think>残留
    故障2: 正常内容<think>思考</think>正常内容重复
    
    处理逻辑:
    1. 优先提取第一个<think>或<tool_call>标签之前的内容(处理故障2)
    2. 如果前面没有内容,则移除所有标签对后,取最后一个</think>或</tool_call>之后的内容
    3. 清理所有残留的单独标签
    
    Args:
        text: 原始文本
        
    Returns:
        str: 处理后的文本
    """
    
    # 查找第一个开始标签的位置
    first_think = text.find('<think>')
    first_tool_call = text.find('<tool_call>')
    
    # 确定第一个标签的位置
    first_tag_pos = -1
    if first_think != -1 and first_tool_call != -1:
        first_tag_pos = min(first_think, first_tool_call)
    elif first_think != -1:
        first_tag_pos = first_think
    elif first_tool_call != -1:
        first_tag_pos = first_tool_call
    
    # 如果标签前有内容(故障2的情况),提取标签前的内容
    if first_tag_pos > 0:
        before_tags = text[:first_tag_pos].strip()
        if before_tags and not before_tags.isspace():
            # 清理可能的残留标签
            before_tags = remove_residual_tags(before_tags)
            return before_tags
    
    # 故障1的情况: 移除配对的标签,保留中间和之后的内容
    # 先移除所有配对标签
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    cleaned = re.sub(r'<tool_call>.*?</tool_call>', '', cleaned, flags=re.DOTALL)
    
    # 查找最后一个结束标签的位置
    last_think_end = cleaned.rfind('</think>')
    last_tool_call_end = cleaned.rfind('</tool_call>')
    
    last_end_tag_pos = max(last_think_end, last_tool_call_end)
    
    # 如果找到结束标签,取其后的内容
    if last_end_tag_pos != -1:
        if last_think_end > last_tool_call_end:
            cleaned = cleaned[last_think_end + len('</think>'):].strip()
        else:
            cleaned = cleaned[last_tool_call_end + len('</tool_call>'):].strip()
    
    # 清理所有残留标签
    cleaned = remove_residual_tags(cleaned)
    
    return cleaned.strip()


def remove_residual_tags(text: str) -> str:
    """
    移除文本中残留的单独标签
    
    Args:
        text: 输入文本
        
    Returns:
        str: 清理后的文本
    """
    # 移除所有开始和结束标签
    text = text.replace('<think>', '')
    text = text.replace('</think>', '')
    text = text.replace('<tool_call>', '')
    text = text.replace('</tool_call>', '')
    
    return text.strip()


def remove_between_markers(text, start_marker, end_marker):
    """
    移除起始标记到结束标记之间的内容(保留用于兼容性)
    
    Args:
        text: 原始文本
        start_marker: 起始标记
        end_marker: 结束标记
        
    Returns:
        str: 处理后的文本
    """
    if not text or not start_marker or not end_marker:
        return text
    
    # 查找最早出现的start_marker
    start_index = text.find(start_marker)
    if start_index == -1:
        return text
    
    # 查找最晚出现的end_marker(从start_index之后开始找)
    end_index = text.rfind(end_marker)
    if end_index == -1 or end_index <= start_index:
        return text
    
    # 计算要删除的结束位置(包含end_marker本身)
    end_index += len(end_marker)
    
    # 删除start_marker到end_marker之间的内容
    result = text[:start_index] + text[end_index:]
    return result


def remove_after_character(text: str, separator: str) -> str:
    """
    移除分隔符之后的内容(保留用于兼容性)
    
    Args:
        text: 原始文本
        separator: 分隔符
        
    Returns:
        str: 分隔符之前的部分
    """
    parts = text.split(separator, 1)
    return parts[0]


def remove_before_character(text: str, separator: str) -> str:
    """
    移除分隔符之前的内容(保留用于兼容性)
    
    Args:
        text: 原始文本
        separator: 分隔符
        
    Returns:
        str: 分隔符之后的部分
    """
    parts = text.split(separator, 1)
    return parts[1] if len(parts) > 1 else text