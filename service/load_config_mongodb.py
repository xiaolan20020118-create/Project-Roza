"""
Load bot_config 和 group_config 自 MongoDB，按 YAML 单元的结构拉平到一个扁平 dict。
- 先查 bot_config（索引 bot_id），再查 group_config（复合索引 bot_id + group_id）。
- 若文档不存在则按预设表结构新建一条，再返回。
- 参考 integrated_workflow 的连接与索引创建逻辑，但直接拷贝必要片段以满足单文件要求。
- 返回值全部是一层 key/value（无嵌套 dict），便于 Dify 代码节点使用。
- 默认群配置使用 group_id "0000"（替代 legacy 的 "default"），自动按 default_groups 映射。
"""
from typing import Any, Dict, List, Optional, Tuple
import pymongo
import re


class ConfigMongoSystem:
    """轻量 Mongo 封装，复用 integrated_workflow 的思路（索引+便捷读写）。"""

    def __init__(
        self,
        mongo_url: str,
        db_name: str = "roza_database",
        bot_collection: str = "bot_config",
        group_collection: str = "group_config",
    ):
        self.client = pymongo.MongoClient(mongo_url)
        self.db = self.client[db_name]
        self.bot_collection = self.db[bot_collection]
        self.group_collection = self.db[group_collection]

        # 按 YAML 单元定义的主键创建索引
        self.bot_collection.create_index([("bot_id", 1)], unique=True)
        self.group_collection.create_index([("bot_id", 1), ("group_id", 1)], unique=True)

    def get_bot_config(self, bot_id: str) -> Dict[str, Any]:
        doc = self.bot_collection.find_one({"bot_id": bot_id})
        if doc:
            return doc
        default_doc = bot_default_document(bot_id)
        self.bot_collection.insert_one(default_doc)
        return default_doc

    def get_group_config(self, bot_id: str, group_id: str) -> Dict[str, Any]:
        doc = self.group_collection.find_one({"bot_id": bot_id, "group_id": group_id})
        if doc:
            return doc
        default_doc = group_default_document(bot_id, group_id)
        self.group_collection.insert_one(default_doc)
        return default_doc


# 暴露表结构（默认模板），便于查看字段。
def bot_default_document(bot_id: str) -> Dict[str, Any]:
    return {
        "bot_id": bot_id,
        "bot_name": "",
        "bot_nickname": "",
        "llm_model": "",
        "basic_info": "",
        "expression_habits": "",
        "think_requirement": "",
        "reply_instruction": "",
        # 函数调用指导（新字段名）
        "function_call_instruction": "",
        "overusage_output": "",
        "error_output": "",
        "admin_users": [],
        "default_groups": [],
        # favor_system 允许自然嵌套，便于后续解析
        "favor_system": {
            "stages": [],
            "split_points": [],
        },
    }


def group_default_document(bot_id: str, group_id: str) -> Dict[str, Any]:
    return {
        "bot_id": bot_id,
        "group_id": group_id,
        "group_info": "",
        "operating_mode": "",
        "favor_system": "",
        "favor_change_display": "",
        "favor_cross_group": "",
        "persona_system": "",
        "persona_cross_group": "",
        "usage_limit_system": "",
        "usage_limit": "",
        "usage_limit_cross_group": "",
        "usage_restrict_admin_users": "",
        "max_input_size": "",
        "memory_system": "",
        "memory_retrieval_number": "",
        "commonsense_system": "",
        "commonsense_cross_group": "",
        "context_system": "",
        "context_pool_size": "",
        "blacklist_system": "",
        "warn_count": "",
        "warn_lifespan": "",
        "block_lifespan": "",
        "blacklist_cross_group": "",
        "blacklist_restrict_admin_users": "",
        "independent_review_system": "",
    }


def to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return []


def compose_prompt(description: str, behavior: str) -> str:
    if description and behavior:
        return f"{description}。{behavior}"
    if description:
        return description
    if behavior:
        return behavior
    return ""


def parse_favor_system(favor_data: Any) -> Tuple[List[str], List[int]]:
    prompts: List[str] = []
    split_points: List[int] = []

    if not isinstance(favor_data, dict):
        return prompts, split_points

    # 解析阶段提示词
    stages = favor_data.get("stages")
    if isinstance(stages, list):
        for stage in stages:
            if isinstance(stage, dict):
                description = to_str(stage.get("description"))
                behavior = to_str(stage.get("behavior"))
                prompts.append(compose_prompt(description, behavior))
            else:
                prompts.append(to_str(stage))
    else:
        stage_map: Dict[int, str] = {}
        for key, value in favor_data.items():
            match = re.search(r"(\d+)", key)
            if not match:
                continue
            idx = int(match.group(1)) - 1
            if idx < 0:
                continue
            if isinstance(value, dict):
                description = to_str(value.get("description"))
                behavior = to_str(value.get("behavior"))
                stage_map[idx] = compose_prompt(description, behavior)
            else:
                stage_map[idx] = to_str(value)
        if stage_map:
            max_idx = max(stage_map.keys())
            prompts = ["" for _ in range(max_idx + 1)]
            for idx, prompt in stage_map.items():
                prompts[idx] = prompt
            while prompts and prompts[-1] == "":
                prompts.pop()

    # 解析分割点
    split_values = favor_data.get("split_points")
    if isinstance(split_values, list):
        for split in split_values:
            try:
                split_points.append(int(split))
            except (TypeError, ValueError):
                continue
    else:
        split_map: Dict[int, int] = {}
        for key, value in favor_data.items():
            if "split" in key or "分割" in key:
                match = re.search(r"(\d+)", key)
                if not match:
                    continue
                idx = int(match.group(1)) - 1
                if idx < 0:
                    continue
                try:
                    split_map[idx] = int(value)
                except (TypeError, ValueError):
                    continue
        if split_map:
            for _, split_val in sorted(split_map.items(), key=lambda x: x[0]):
                split_points.append(split_val)

    return prompts, split_points


def derive_mode_prompt(operating_mode: str) -> str:
    if operating_mode == "chat":
        return "你要在群聊内提供情感陪伴，与群聊成员互动，活跃群内气氛"
    return "你负责在群聊内根据知识库内容进行问题的答疑，不允许与群内成员闲聊"


def main(
    mongo_url: str,
    bot_id: str,
    user_id: str,
    group_id: Optional[str] = "",
    db_name: str = "roza_database",
    bot_collection: str = "bot_config",
    group_collection: str = "group_config",
) -> Dict[str, str]:
    repo = ConfigMongoSystem(
        mongo_url=mongo_url,
        db_name=db_name,
        bot_collection=bot_collection,
        group_collection=group_collection,
    )

    error_messages = ""

    bot_config = repo.get_bot_config(bot_id)
    if not bot_config:
        error_messages = "bot_config not found"

    default_groups = [to_str(x) for x in as_list(bot_config.get("default_groups"))]
    admin_users = [to_str(x) for x in as_list(bot_config.get("admin_users"))]

    is_private_chat = "false"
    is_default_group = "false"

    if not group_id:
        group_id = "0001"
        is_private_chat = "true"
    else:
        group_id = to_str(group_id)
        if group_id in default_groups:
            is_default_group = "true"

    # default_group 时使用 0000 作为 group_config 索引
    group_lookup_id = "0000" if is_default_group == "true" else group_id
    group_config = repo.get_group_config(bot_id, group_lookup_id)
    if not group_config:
        if error_messages:
            error_messages += "; group_config not found"
        else:
            error_messages = "group_config not found"

    is_user_admin = "true" if to_str(user_id) in admin_users else "false"

    # 优先读取顶层数组字段，缺失时回落 favor_system 解析
    raw_prompts = bot_config.get("favor_prompts")
    if isinstance(raw_prompts, list):
        favor_prompts = [to_str(x) for x in raw_prompts]
    else:
        favor_prompts = []

    raw_splits = bot_config.get("favor_split_points")
    favor_split_points: List[int] = []
    if isinstance(raw_splits, list):
        for val in raw_splits:
            try:
                favor_split_points.append(int(val))
            except (TypeError, ValueError):
                continue

    # 如果顶层字段未提供，则解析 favor_system
    if not favor_prompts and not favor_split_points:
        favor_prompts, favor_split_points = parse_favor_system(bot_config.get("favor_system"))

    operating_mode = to_str(group_config.get("operating_mode"))
    mode_prompt = derive_mode_prompt(operating_mode)

    result: Dict[str, Any] = {
        "basic_info": to_str(bot_config.get("basic_info")),
        "blacklist_cross_group": to_str(group_config.get("blacklist_cross_group")),
        "blacklist_restrict_admin_users": to_str(group_config.get("blacklist_restrict_admin_users")),
        "blacklist_system": to_str(group_config.get("blacklist_system")),
        "block_lifespan": to_str(group_config.get("block_lifespan")),
        "bot_name": to_str(bot_config.get("bot_name")),
        "bot_nickname": to_str(bot_config.get("bot_nickname")),
        "commonsense_cross_group": to_str(group_config.get("commonsense_cross_group")),
        "commonsense_system": to_str(group_config.get("commonsense_system")),
        "config_search_filter": bot_id,
        "context_pool_size": to_str(group_config.get("context_pool_size")),
        "context_system": to_str(group_config.get("context_system")),
        "error_messages": error_messages,
        "error_output": to_str(bot_config.get("error_output")),
        "expression_habits": to_str(bot_config.get("expression_habits")),
        "favor_change_display": to_str(group_config.get("favor_change_display")),
        "favor_cross_group": to_str(group_config.get("favor_cross_group")),
        "favor_prompts": favor_prompts,
        "favor_split_points": favor_split_points,
        "favor_system": to_str(group_config.get("favor_system")),
        "function_call_instruction": to_str(bot_config.get("function_call_instruction")),
        "group_id": group_id,
        "group_info": to_str(group_config.get("group_info")),
        "independent_review_system": to_str(group_config.get("independent_review_system")),
        "is_default_group": is_default_group,
        "is_private_chat": is_private_chat,
        "is_user_admin": is_user_admin,
        "llm_model": to_str(bot_config.get("llm_model")),
        "max_input_size": to_str(group_config.get("max_input_size")),
        "memory_retrieval_number": to_str(group_config.get("memory_retrieval_number")),
        "memory_system": to_str(group_config.get("memory_system")),
        "mode_prompt": mode_prompt,
        "operating_mode": operating_mode,
        "overusage_output": to_str(bot_config.get("overusage_output")),
        "persona_cross_group": to_str(group_config.get("persona_cross_group")),
        "persona_system": to_str(group_config.get("persona_system")),
        "reply_instruction": to_str(bot_config.get("reply_instruction")),
        "think_requirement": to_str(bot_config.get("think_requirement")),
        "usage_limit": to_str(group_config.get("usage_limit")),
        "usage_limit_cross_group": to_str(group_config.get("usage_limit_cross_group")),
        "usage_limit_system": to_str(group_config.get("usage_limit_system")),
        "usage_restrict_admin_users": to_str(group_config.get("usage_restrict_admin_users")),
        "warn_count": to_str(group_config.get("warn_count")),
        "warn_lifespan": to_str(group_config.get("warn_lifespan")),
    }

    return result
