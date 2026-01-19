"""
消息预处理：指令判定 + 时间/键值处理。
输入：bot_id, group_id, commonsense_cross_group, user_query。
输出：包含 command（是指令→"command"，否则"chat"）、时间信息、commonsense_search_key、user_query、quoted_message。
"""
from datetime import datetime, timezone, timedelta
import re
from typing import Dict, Any, List


def _detect_command(user_query: str) -> str:
    """Return "command" iff input contains a whitespace- or start-delimited " /Roza." prefix."""
    return "command" if re.search(r"(?:^|\s)/Roza\." , user_query) else "chat"


def _get_beijing_time_info() -> Dict[str, Any]:
    """Return Beijing time info with numeric timestamp and string date parts."""
    beijing_tz = timezone(timedelta(hours=8))
    now = datetime.now(beijing_tz)
    year_str = f"{now.year:04d}"
    month_str = f"{now.month:02d}"
    day_str = f"{now.day:02d}"
    hour_str = f"{now.hour:02d}"
    minute_str = f"{now.minute:02d}"
    second_str = f"{now.second:02d}"
    return {
        "timestamp": int(now.timestamp()),
        "year": year_str,
        "month": month_str,
        "day": day_str,
        "hour_minute": hour_str + minute_str,
        "weekday": str(now.weekday() + 1),
        "formatted_time": f"{year_str}-{month_str}-{day_str} {hour_str}:{minute_str}:{second_str}",
    }


def _parse_query_message(query: str) -> Dict[str, str]:
    """Extract user_query and quoted_message if present."""
    if "Referenced message: " in query and "User's message: " in query:
        user_query = _remove_before_character(query, "User's message: ")
        quoted_message_part = _remove_after_character(query, "User's message: ")
        quoted_message = _remove_before_character(quoted_message_part, "Referenced message: ")
    else:
        user_query = query
        quoted_message = ""
    return {"user_query": user_query, "quoted_message": quoted_message}


def _generate_commonsense_search_key(bot_id: str, group_id: str, commonsense_cross_group: Any) -> str:
    return f"{bot_id}:self" if commonsense_cross_group else f"{bot_id}:{group_id}"


def _remove_after_character(text: str, separator: str) -> str:
    parts = text.split(separator, 1)
    return parts[0]


def _remove_before_character(text: str, separator: str) -> str:
    parts = text.split(separator, 1)
    return parts[1] if len(parts) > 1 else text


def _detect_image_files(sys_files: List[Any]) -> bool:
    """Check if sys_files contains any image type."""
    if not sys_files:
        return False
    for file in sys_files:
        if isinstance(file, dict) and file.get("type") == "image":
            return True
    return False


def main(bot_id: str, group_id: str, commonsense_cross_group: Any, user_query: str, sys_files: List[Any], llm_model: str) -> Dict[str, Any]:
    """
    消息预处理入口。
    Args:
        bot_id: 机器人ID
        group_id: 群组ID
        commonsense_cross_group: 是否跨群（bool/int/str）
        user_query: 用户输入（可能含引用）
        sys_files: 系统文件数组
        llm_model: LLM模型名称
    Returns:
        dict: command + 时间 + commonsense 键 + 原始/引用消息 + llm_model
    """
    message_info = _parse_query_message(user_query)
    command = _detect_command(message_info["user_query"])
    time_info = _get_beijing_time_info()
    commonsense_key = _generate_commonsense_search_key(bot_id, group_id, commonsense_cross_group)

    # Detect image files and adjust model
    if _detect_image_files(sys_files):
        llm_model = "vision_llm"

    return {
        "command": command,  # type: str
        "timestamp": time_info["timestamp"],  # type: int
        "year": time_info["year"],  # type: str
        "month": time_info["month"],  # type: str
        "day": time_info["day"],  # type: str
        "hour_minute": time_info["hour_minute"],  # type: str
        "weekday": time_info["weekday"],  # type: str
        "formatted_time": time_info["formatted_time"],  # type: str
        "commonsense_search_key": commonsense_key,  # type: str
        "user_query": message_info["user_query"],  # type: str
        "quoted_message": message_info["quoted_message"],  # type: str
        "llm_model": llm_model,  # type: str
    }
