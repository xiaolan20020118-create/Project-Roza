"""
Fallback config loader for no-Mongo scenarios.
Loads only the default group (group_id="0000") config for the given bot_id.
No external YAML dependency; minimal parsing compatible with existing configs.
"""
import re
from typing import List, Tuple, Iterable


def parse_scalar(block: str, key: str) -> str:
    m = re.search(rf'^\s*{re.escape(key)}:\s*"([^\"]*)"\s*$', block, re.MULTILINE)
    if m:
        return m.group(1).strip()
    m = re.search(rf'^\s*{re.escape(key)}:\s*([^\n#]+)', block, re.MULTILINE)
    return m.group(1).strip() if m else ""


def parse_block_scalar(block: str, key: str) -> str:
    lines = block.splitlines()
    for idx, line in enumerate(lines):
        m = re.match(rf'^(\s*){re.escape(key)}:\s*\|\s*$', line)
        if not m:
            continue
        key_indent = len(m.group(1))
        content_lines: List[str] = []
        for content in lines[idx + 1 :]:
            if content.strip() == "":
                content_lines.append("")
                continue
            indent = len(content) - len(content.lstrip(" "))
            if indent <= key_indent:
                break
            strip_len = key_indent + 2 if indent >= key_indent + 2 else key_indent
            content_lines.append(content[strip_len:])
        return "\n".join(content_lines).rstrip()
    return ""


def parse_list(block: str, key: str) -> List[str]:
    m = re.search(rf'^\s*{re.escape(key)}:\s*\n((?:\s+-.*\n?)*)', block, re.MULTILINE)
    if not m:
        return []
    items: List[str] = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line.startswith('-'):
            continue
        val = line[1:].strip()
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        items.append(val)
    return items


def _iter_units(yaml_text: str) -> Iterable[Tuple[str, str, str]]:
    explicit_pattern = r'(?:^|\n)-\s*bot_id:\s*"?(?P<bot_id>[^"\n]+)"?\s*\n(?P<body>.*?)(?=\n-\s*(?:bot_id|search_key):|\Z)'
    for m in re.finditer(explicit_pattern, yaml_text, re.DOTALL):
        body = m.group("body")
        group_id = parse_scalar(body, "group_id")
        yield m.group("bot_id").strip(), group_id.strip(), body.strip()

    legacy_pattern = r'(?:^|\n)-\s*search_key:\s*"(?P<search_key>[^"]+)"\s*\n(?P<body>.*?)(?=\n-\s*(?:search_key|bot_id):|\Z)'
    for m in re.finditer(legacy_pattern, yaml_text, re.DOTALL):
        sk = m.group("search_key")
        if ":" in sk:
            bot_id, group_id = sk.split(":", 1)
        else:
            bot_id, group_id = sk, ""
        yield bot_id.strip(), group_id.strip(), m.group("body").strip()

    if not re.search(r'^\s*-\s*(bot_id|search_key):', yaml_text, re.MULTILINE):
        bot_id = parse_scalar(yaml_text, "bot_id")
        group_id = parse_scalar(yaml_text, "group_id")
        search_key = parse_scalar(yaml_text, "search_key")
        if not bot_id and search_key:
            if ":" in search_key:
                bot_id, group_id = search_key.split(":", 1)
            else:
                bot_id, group_id = search_key, ""
        if bot_id:
            yield bot_id.strip(), group_id.strip(), yaml_text.strip()


def _find_unit_block(yaml_text: str, bot_id: str, group_id: str) -> str:
    for b_id, g_id, body in _iter_units(yaml_text):
        if b_id == bot_id and g_id == group_id:
            return body
    return ""


def main(bot_config_yaml: str, group_config_yaml: str, bot_id: str, user_id: str = "") -> dict:
    """Load bot config and the bot's default group (group_id="0000")."""
    error_messages = ""

    bot_block = _find_unit_block(bot_config_yaml, bot_id, "")
    if not bot_block:
        error_messages = "bot_config not found"

    bot_name = parse_scalar(bot_block, "bot_name")
    bot_nickname = parse_scalar(bot_block, "bot_nickname")
    llm_model = parse_scalar(bot_block, "llm_model")
    overusage_output = parse_scalar(bot_block, "overusage_output")
    error_output = parse_scalar(bot_block, "error_output")
    basic_info_str = parse_block_scalar(bot_block, "basic_info")
    expression_habits_str = parse_block_scalar(bot_block, "expression_habits")
    think_requirement_content = parse_block_scalar(bot_block, "think_requirement")
    reply_instruction = parse_block_scalar(bot_block, "reply_instruction")
    function_call_instruction = parse_block_scalar(bot_block, "function_call_instruction")
    favor_prompts = parse_list(bot_block, "favor_prompts")
    favor_split_points = [int(x) for x in parse_list(bot_block, "favor_split_points") if str(x).strip().lstrip('-').isdigit()]

    admin_ids = parse_list(bot_block, "admin_users")
    default_group_ids = parse_list(bot_block, "default_groups")
    is_user_admin = "true" if user_id in admin_ids else "false"

    group_id = "0000"
    group_block = _find_unit_block(group_config_yaml, bot_id, group_id)
    if not group_block:
        error_messages = (error_messages + "; " if error_messages else "") + "group_config not found"

    group_info = parse_scalar(group_block, "group_info")
    operating_mode = parse_scalar(group_block, "operating_mode")
    favor_system = parse_scalar(group_block, "favor_system")
    favor_cross_group = parse_scalar(group_block, "favor_cross_group")
    persona_system = parse_scalar(group_block, "persona_system")
    persona_cross_group = parse_scalar(group_block, "persona_cross_group")
    usage_limit_system = parse_scalar(group_block, "usage_limit_system")
    usage_limit = parse_scalar(group_block, "usage_limit")
    usage_limit_cross_group = parse_scalar(group_block, "usage_limit_cross_group")
    usage_restrict_admin_users = parse_scalar(group_block, "usage_restrict_admin_users")
    max_input_size = parse_scalar(group_block, "max_input_size")
    memory_system = parse_scalar(group_block, "memory_system")
    memory_retrieval_number = parse_scalar(group_block, "memory_retrieval_number")
    commonsense_system = parse_scalar(group_block, "commonsense_system")
    commonsense_cross_group = parse_scalar(group_block, "commonsense_cross_group")
    favor_change_display = parse_scalar(group_block, "favor_change_display")
    context_system = parse_scalar(group_block, "context_system")
    context_pool_size = parse_scalar(group_block, "context_pool_size")
    blacklist_system = parse_scalar(group_block, "blacklist_system")
    warn_count = parse_scalar(group_block, "warn_count")
    warn_lifespan = parse_scalar(group_block, "warn_lifespan")
    blacklist_cross_group = parse_scalar(group_block, "blacklist_cross_group")
    blacklist_restrict_admin_users = parse_scalar(group_block, "blacklist_restrict_admin_users")
    block_lifespan = parse_scalar(group_block, "block_lifespan")
    independent_review_system = parse_scalar(group_block, "independent_review_system")

    mode_prompt = "你要在群聊内提供情感陪伴，与群聊成员互动，活跃群内气氛" if operating_mode == "chat" else "你负责在群聊内根据知识库内容进行问题的答疑，不允许与群内成员闲聊"

    return {
        "basic_info": basic_info_str,
        "blacklist_cross_group": blacklist_cross_group,
        "blacklist_restrict_admin_users": blacklist_restrict_admin_users,
        "blacklist_system": blacklist_system,
        "block_lifespan": block_lifespan,
        "bot_name": bot_name,
        "bot_nickname": bot_nickname,
        "commonsense_cross_group": commonsense_cross_group,
        "commonsense_system": commonsense_system,
        "config_search_filter": bot_id,
        "context_pool_size": context_pool_size,
        "context_system": context_system,
        "error_messages": error_messages,
        "error_output": error_output,
        "expression_habits": expression_habits_str,
        "favor_change_display": favor_change_display,
        "favor_cross_group": favor_cross_group,
        "favor_prompts": favor_prompts,
        "favor_split_points": favor_split_points,
        "favor_system": favor_system,
        "function_call_instruction": function_call_instruction,
        "group_id": group_id,
        "group_info": group_info,
        "independent_review_system": independent_review_system,
        "is_default_group": "true",
        "is_private_chat": "false",
        "is_user_admin": is_user_admin,
        "llm_model": llm_model,
        "max_input_size": max_input_size,
        "memory_retrieval_number": memory_retrieval_number,
        "memory_system": memory_system,
        "mode_prompt": mode_prompt,
        "operating_mode": operating_mode,
        "overusage_output": overusage_output,
        "persona_cross_group": persona_cross_group,
        "persona_system": persona_system,
        "reply_instruction": reply_instruction,
        "think_requirement": think_requirement_content,
        "usage_limit": usage_limit,
        "usage_limit_cross_group": usage_limit_cross_group,
        "usage_limit_system": usage_limit_system,
        "usage_restrict_admin_users": usage_restrict_admin_users,
        "warn_count": warn_count,
        "warn_lifespan": warn_lifespan,
    }
