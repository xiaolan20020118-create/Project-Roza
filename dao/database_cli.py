#!/usr/bin/env python3
"""
Roza 数据库管理 CLI 工具

整合功能：
    1. 本地运行指令系统 (get/set/clear/rank)
    2. 配置文件导入 (YAML -> MongoDB)
    3. 数据库表结构更新 (字符串字段 -> 数组字段)

支持指令格式：
    /Roza.get.{type}[.field] [target] [...]
    /Roza.set.{type}.field [target] [value] [...]
    /Roza.clear.{type}[.field] [target] [...]
    /Roza.rank.{type}.field [limit] [...]

类型支持：
    favor - 好感度
    usage - 用量统计
    memory - 长期记忆
    context - 上下文历史
    persona - 用户画像
    blacklist - 黑名单
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pymongo


# =============================================================================
# ASCII Art Banner
# =============================================================================

# 科技蓝 (RGB: 0, 247, 255)
ROZA_BLUE = "[38;2;0;247;255m"
ROZA_BOLD = "[1m"
ROZA_RESET = "[0m"

ROZA_BANNER = r"""
██████╗  ██████╗ ███████╗███████╗  █████╗
██╔══██╗██╔═══██╗██╔════╝██╔════╝ ██╔══██╗
██████╔╝██║   ██║███████╗███████╗███████║
██╔══██╗██║   ██║╚════██║╚════██║██╔══██║
██║  ██║╚██████╔╝███████║███████║██║  ██║
╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚══════╝╚═╝  ╚═╝
        ═════════════════════════════
            数据库管理 CLI 工具
        ═════════════════════════════
"""


# =============================================================================
# MongoDB System
# =============================================================================

class MongoDBSystem:
    """MongoDB helper supporting multiple collections."""

    def __init__(self, mongo_url: str, db_name: str = "roza_database"):
        self.client = pymongo.MongoClient(mongo_url)
        self.db = self.client[db_name]
        self._user_data_collection = self.db["user_data"]

    @property
    def collection(self):
        """Default collection for user data operations."""
        return self._user_data_collection

    def get_collection(self, collection_name: str):
        """Get a specific collection by name."""
        return self.db[collection_name]

    def find(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        return list(self._user_data_collection.find(query))

    def find_one(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self._user_data_collection.find_one(query)

    def aggregate(self, pipeline: List[Dict[str, Any]]) -> pymongo.command_cursor.CommandCursor:
        """执行聚合管道查询"""
        return self._user_data_collection.aggregate(pipeline)

    def update_many(self, query: Dict[str, Any], updates: Dict[str, Any]) -> Tuple[int, int]:
        result = self._user_data_collection.update_many(query, {"$set": updates})
        return result.matched_count, result.modified_count

    def update_one(self, query: Dict[str, Any], updates: Dict[str, Any]) -> Tuple[int, int]:
        result = self._user_data_collection.update_one(query, {"$set": updates})
        return result.matched_count, result.modified_count

    def test_connection(self) -> bool:
        """测试数据库连接是否正常"""
        try:
            self.client.list_database_names()
            return True
        except Exception:
            return False

    def close(self):
        self.client.close()


# =============================================================================
# YAML Parsing (from sync_configs_to_mongo.py)
# =============================================================================

def _iter_units_with_key(yaml_text: str) -> Iterable[Tuple[str, str, str]]:
    """Yield (bot_id, group_id, block) supporting explicit and legacy formats."""

    # Explicit bot_id/group_id form (preferred)
    explicit_pattern = r'(?:^|\n)-\s*bot_id:\s*"?(?P<bot_id>[^"\n]+)"?\s*\n(?P<body>.*?)(?=\n-\s*(?:bot_id|search_key):|\Z)'
    for m in re.finditer(explicit_pattern, yaml_text, re.DOTALL):
        body = m.group("body").strip()
        group_id = _parse_scalar(body, "group_id")
        yield m.group("bot_id").strip(), group_id.strip(), body

    # Legacy search_key form: search_key: "bot:group"
    legacy_pattern = r'(?:^|\n)-\s*search_key:\s*"(?P<search_key>[^"]+)"\s*\n(?P<body>.*?)(?=\n-\s*(?:search_key|bot_id):|\Z)'
    for m in re.finditer(legacy_pattern, yaml_text, re.DOTALL):
        sk = m.group("search_key")
        if ":" in sk:
            bot_id, group_id = sk.split(":", 1)
        else:
            bot_id, group_id = sk, ""
        yield bot_id.strip(), group_id.strip(), m.group("body").strip()

    # Fallback: single-document YAML with bot_id/group_id keys
    if not re.search(r'^\s*-\s*(bot_id|search_key):', yaml_text, re.MULTILINE):
        bot_id = _parse_scalar(yaml_text, "bot_id")
        group_id = _parse_scalar(yaml_text, "group_id")
        search_key = _parse_scalar(yaml_text, "search_key")
        if not bot_id and search_key:
            if ":" in search_key:
                bot_id, group_id = search_key.split(":", 1)
            else:
                bot_id, group_id = search_key, ""
        if bot_id:
            yield bot_id.strip(), group_id.strip(), yaml_text.strip()


def _parse_scalar(block: str, key: str) -> str:
    m = re.search(rf'^\s*{re.escape(key)}:\s*"([^"]*)"\s*$', block, re.MULTILINE)
    if m:
        return m.group(1).strip()
    m = re.search(rf'^\s*{re.escape(key)}:\s*([^\n#]+)', block, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _parse_block_scalar(block: str, key: str) -> str:
    lines = block.splitlines()
    for idx, line in enumerate(lines):
        m = re.match(rf'^(\s*){re.escape(key)}:\s*\|\s*$', line)
        if not m:
            continue
        key_indent = len(m.group(1))
        content_lines: List[str] = []
        for content in lines[idx + 1:]:
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


def _parse_list(block: str, key: str) -> List[str]:
    m = re.search(rf'^\s*{re.escape(key)}:\s*\n((?:\s+-.*\n?)*)', block, re.MULTILINE)
    if not m:
        return []
    items = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line.startswith('-'):
            continue
        val = line[1:].strip()
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        items.append(val)
    return items


def _parse_bool(block: str, key: str) -> bool:
    """
    解析布尔类型的配置字段
    支持格式: true/false, 1/0
    返回 Python bool 类型
    """
    scalar = _parse_scalar(block, key).lower()
    if scalar in ("true", "1"):
        return True
    if scalar in ("false", "0"):
        return False
    return False


def _upsert_bot_configs(collection, yaml_text: str):
    for bot_id, group_id, block in _iter_units_with_key(yaml_text):
        if not bot_id:
            continue
        doc: Dict[str, object] = {
            "bot_id": bot_id,
            # 基本信息
            "bot_name": _parse_scalar(block, "bot_name"),
            "bot_nickname": _parse_scalar(block, "bot_nickname"),
            "llm_model": _parse_scalar(block, "llm_model"),
            "basic_info": _parse_block_scalar(block, "basic_info"),
            # 表达/思考/回复/工具
            "expression_habits": _parse_block_scalar(block, "expression_habits"),
            "think_requirement": _parse_block_scalar(block, "think_requirement"),
            "reply_instruction": _parse_block_scalar(block, "reply_instruction"),
            "function_call_instruction": _parse_block_scalar(block, "function_call_instruction"),
            # 常规输出（列表格式）
            "overusage_output": _parse_list(block, "overusage_output"),
            "error_output": _parse_list(block, "error_output"),
            "overinput_output": _parse_list(block, "overinput_output"),
            # 管理/默认群/好感度
            "admin_users": _parse_list(block, "admin_users"),
            "default_groups": _parse_list(block, "default_groups"),
            "favor_prompts": _parse_list(block, "favor_prompts"),
            "favor_split_points": [int(x) for x in _parse_list(block, "favor_split_points") if str(x).strip().lstrip('-').isdigit()],
        }
        collection.update_one({"bot_id": bot_id}, {"$set": doc}, upsert=True)


def _upsert_group_configs(collection, yaml_text: str):
    for bot_id, group_id, block in _iter_units_with_key(yaml_text):
        if not bot_id or not group_id:
            continue
        doc: Dict[str, object] = {
            "bot_id": bot_id,
            "group_id": group_id,
            # 群配置顺序参考 group_eg.yml
            "group_info": _parse_scalar(block, "group_info"),
            "operating_mode": _parse_scalar(block, "operating_mode"),
            # 布尔字段使用 _parse_bool
            "favor_system": _parse_bool(block, "favor_system"),
            "favor_change_display": _parse_bool(block, "favor_change_display"),
            "favor_cross_group": _parse_bool(block, "favor_cross_group"),
            "persona_system": _parse_bool(block, "persona_system"),
            "persona_cross_group": _parse_bool(block, "persona_cross_group"),
            "usage_limit_system": _parse_bool(block, "usage_limit_system"),
            "usage_limit": _parse_scalar(block, "usage_limit"),
            "usage_limit_cross_group": _parse_bool(block, "usage_limit_cross_group"),
            "usage_restrict_admin_users": _parse_bool(block, "usage_restrict_admin_users"),
            "max_input_size": _parse_scalar(block, "max_input_size"),
            "memory_system": _parse_bool(block, "memory_system"),
            "memory_retrieval_number": _parse_scalar(block, "memory_retrieval_number"),
            "context_system": _parse_bool(block, "context_system"),
            "context_pool_size": _parse_scalar(block, "context_pool_size"),
            "commonsense_system": _parse_bool(block, "commonsense_system"),
            "commonsense_cross_group": _parse_bool(block, "commonsense_cross_group"),
            "blacklist_system": _parse_bool(block, "blacklist_system"),
            "warn_count": _parse_scalar(block, "warn_count"),
            "warn_lifespan": _parse_scalar(block, "warn_lifespan"),
            "block_lifespan": _parse_scalar(block, "block_lifespan"),
            "blacklist_cross_group": _parse_bool(block, "blacklist_cross_group"),
            "blacklist_restrict_admin_users": _parse_bool(block, "blacklist_restrict_admin_users"),
            "independent_review_system": _parse_bool(block, "independent_review_system"),
        }
        collection.update_one({"bot_id": bot_id, "group_id": group_id}, {"$set": doc}, upsert=True)


def _read_yaml(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="gb18030")


def _collect_yaml_files(directory: Path) -> List[Path]:
    if not directory.is_dir():
        raise FileNotFoundError(f"目录不存在: {directory}")
    files = list(directory.rglob("*.yml")) + list(directory.rglob("*.yaml"))
    return sorted(set(files))


def _count_units(yaml_text: str, *, require_group_id: bool) -> int:
    count = 0
    for bot_id, group_id, _ in _iter_units_with_key(yaml_text):
        if not bot_id:
            continue
        if require_group_id and not group_id:
            continue
        count += 1
    return count


def _sync_files(collection, files: Iterable[Path], is_bot: bool) -> int:
    total_units = 0
    for path in files:
        try:
            yaml_text = _read_yaml(path)
            units = _count_units(yaml_text, require_group_id=not is_bot)
            if is_bot:
                _upsert_bot_configs(collection, yaml_text)
            else:
                _upsert_group_configs(collection, yaml_text)
            total_units += units
            print(f"[OK] {path.name}: {units} 条")
        except Exception as exc:
            print(f"[ERR] {path}: {exc}")
    return total_units


def _migrate_string_to_array(collection) -> int:
    """将数据库中的字符串格式字段迁移为数组格式。"""
    migrated_count = 0
    skipped_count = 0

    for doc in collection.find():
        updates = {}
        need_update = False
        bot_id = doc.get("bot_id", "unknown")

        fields_to_migrate = [
            ("overusage_output", "魔法的时间结束啦，请明天再来吧"),
            ("error_output", "刚才走神了，可以再说一遍吗？"),
            ("overinput_output", "这么长谁看的过来啦……"),
        ]

        for field_name, default_value in fields_to_migrate:
            current_value = doc.get(field_name)

            if isinstance(current_value, list):
                cleaned_array = [v for v in current_value if isinstance(v, str) and v.strip()]
                if len(cleaned_array) != len(current_value):
                    updates[field_name] = cleaned_array if cleaned_array else [default_value]
                    need_update = True
                continue

            if isinstance(current_value, str) and current_value.strip():
                updates[field_name] = [current_value.strip()]
                need_update = True
                continue

            if current_value is None or (isinstance(current_value, str) and not current_value.strip()):
                updates[field_name] = [default_value]
                need_update = True
                continue

        if need_update:
            collection.update_one({"_id": doc["_id"]}, {"$set": updates})
            migrated_count += 1
            print(f"[迁移] {bot_id}:")
            for field_name, _ in fields_to_migrate:
                if field_name in updates:
                    print(f"  - {field_name}: {repr(updates[field_name])}")
        else:
            skipped_count += 1

    print(f"\n迁移完成！")
    print(f"  - 已迁移文档数: {migrated_count}")
    print(f"  - 跳过文档数（已是数组格式）: {skipped_count}")

    return migrated_count


# =============================================================================
# Command Parsing
# =============================================================================

CommandParts = Tuple[str, str, Optional[str], bool, List[str]]


def parse_command(user_query: str) -> CommandParts:
    """Parse a command like /Roza.set.usage.total_tokens.any ...

    Returns: (action, type_key, field, has_any, params)
    """
    trimmed = user_query.strip()
    if not trimmed.startswith("/Roza."):
        return "", "", None, False, []

    tokens = trimmed.split()
    command_token = tokens[0]
    params = tokens[1:]

    segments = command_token.lstrip("/").split(".")
    if len(segments) < 3 or segments[0] != "Roza":
        return "", "", None, False, []

    action = segments[1]
    type_key = segments[2]
    field = None
    has_any = False

    if segments[-1] == "any":
        has_any = True
        if len(segments) > 4:
            field = ".".join(segments[3:-1])
        elif len(segments) == 4:
            pass
    else:
        if len(segments) > 3:
            field = ".".join(segments[3:])

    if not params and has_any:
        params = ["%:%:%"]

    if not params and not has_any:
        params = ["all"]

    return action, type_key, field, has_any, params


# =============================================================================
# Type Defaults
# =============================================================================

RANK_FIELDS = {
    "favor": ["favor_value", "last_favor_change"],
    "usage": [
        "daily_usage_count",
        "total_usage.total_chat_count",
        "total_usage.total_tokens",
        "total_usage.total_prompt_token",
        "total_usage.total_output_token",
    ],
    "memory": ["history_entries"],
    "blacklist": ["block_stats.block_count"],
}


def _resolve_rank_field(type_key: str, field: str) -> Optional[str]:
    """解析 rank 字段，使用叶子节点匹配"""
    if not field:
        return None

    if type_key not in RANK_FIELDS:
        return None

    input_leaf = field.split(".")[-1]

    for full_field in RANK_FIELDS[type_key]:
        if field == full_field:
            return full_field
        full_leaf = full_field.split(".")[-1]
        if input_leaf == full_leaf:
            return full_field

    return None


TYPE_DEFAULTS = {
    "favor": {
        "fields": ["favor_value", "last_favor_change"],
        "clear": {"favor_value": 0, "last_favor_change": 0},
    },
    "usage": {
        "fields": [
            "daily_usage_count",
            "total_usage.total_chat_count",
            "total_usage.total_tokens",
            "total_usage.total_prompt_token",
            "total_usage.total_output_token",
        ],
        "clear": {"daily_usage_count": 0},
    },
    "memory": {
        "fields": ["long_term_memory"],
        "clear": {"long_term_memory": []},
    },
    "context": {
        "fields": ["history_entries"],
        "clear": {"history_entries": []},
    },
    "persona": {
        "fields": [
            "persona_attributes.basic_info",
            "persona_attributes.living_habits",
            "persona_attributes.psychological_traits",
            "persona_attributes.interests_preferences",
            "persona_attributes.dislikes",
            "persona_attributes.ai_expectations",
            "persona_attributes.memory_points",
        ],
        "clear": {
            "persona_attributes": {
                "basic_info": "",
                "living_habits": "",
                "psychological_traits": "",
                "interests_preferences": "",
                "dislikes": "",
                "ai_expectations": "",
                "memory_points": "",
            }
        },
    },
    "blacklist": {
        "fields": ["block_stats.block_status", "block_stats.block_count", "block_stats.last_operate_time"],
        "clear": {
            "block_stats": {
                "block_status": True,
                "block_count": 0,
                "last_operate_time": datetime.utcnow().isoformat(),
            }
        },
    },
}


# =============================================================================
# Helper Functions
# =============================================================================

def _get_nested(doc: Dict[str, Any], dotted: str) -> Any:
    parts = dotted.split(".")
    cur: Any = doc
    for part in parts:
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _format_context(entries: List[Dict[str, Any]], pool_size: int) -> str:
    if not entries:
        return "暂无记录"
    recent = entries[-pool_size:] if pool_size > 0 else entries
    lines = []
    for item in recent:
        user_name = item.get("user_name", "对方")
        query = item.get("user_query", "")
        created_at = item.get("created_at", "")
        output = item.get("output", {})
        resp = output.get("response", str(output)) if isinstance(output, dict) else str(output)
        lines.append(f"{created_at} {user_name}: {query}\n回复: {resp}")
    return "\n\n".join(lines)


def _format_persona(attrs: Dict[str, Any]) -> str:
    if not isinstance(attrs, dict):
        return "数据格式错误"
    keys = [
        ("basic_info", "基本信息"),
        ("living_habits", "生活习惯"),
        ("psychological_traits", "心理特征"),
        ("interests_preferences", "兴趣偏好"),
        ("dislikes", "反感点"),
        ("ai_expectations", "对AI的期望"),
        ("memory_points", "希望记住的信息"),
    ]
    lines = [f"{label}: {attrs.get(key, '')}" for key, label in keys if key in attrs]
    return "\n".join(lines) if lines else "暂无数据"


def _format_usage(total: Dict[str, Any], daily: Any) -> str:
    if not isinstance(total, dict):
        total = {}
    lines = [f"今日用量: {daily}"]
    lines.append(f"总对话数: {total.get('total_chat_count', 0)}")
    lines.append(f"总Token: {total.get('total_tokens', 0)}")
    lines.append(f"输入Token: {total.get('total_prompt_token', 0)}")
    lines.append(f"输出Token: {total.get('total_output_token', 0)}")
    return "\n".join(lines)


def _format_blacklist(stats: Dict[str, Any]) -> str:
    if not isinstance(stats, dict):
        return "数据格式错误"
    status_text = "允许" if stats.get("block_status", True) else "封锁"
    return (
        f"状态: {status_text}\n"
        f"违规次数: {stats.get('block_count', 0)}\n"
        f"最后操作: {stats.get('last_operate_time', '')}"
    )


def _build_query(bot_id: str, group_id: str, target: str, has_any: bool) -> Dict[str, Any]:
    if not has_any:
        if target == "all":
            return {"bot_id": bot_id, "group_id": group_id}
        return {"bot_id": bot_id, "group_id": group_id, "user_id": target}

    parts = target.split(":")
    bid, gid, uid = (parts + ["", "", ""])[:3]
    query: Dict[str, Any] = {}
    if bid and bid != "%":
        query["bot_id"] = bid
    if gid and gid != "%":
        query["group_id"] = gid
    if uid and uid != "%":
        query["user_id"] = uid
    return query


def _validate_set_value(type_key: str, field: str, value: Any) -> Any:
    if type_key == "favor" and field in {"favor_value", "last_favor_change"}:
        return int(value)
    if type_key == "blacklist" and field == "block_count":
        return int(value)
    if type_key == "blacklist" and field == "block_status":
        if str(value).lower() in {"true", "1"}:
            return True
        if str(value).lower() in {"false", "0"}:
            return False
        raise ValueError("block_status必须是布尔值 (true/false)")
    return str(value)


def _extract_value(doc: Dict[str, Any], type_key: str, field: Optional[str], pool_size: int) -> str:
    if field:
        val = _get_nested(doc, field)
        return "字段不存在" if val is None else json.dumps(val, ensure_ascii=False)

    if type_key == "favor":
        return f"好感度: {doc.get('favor_value', 0)}\n最后变化: {doc.get('last_favor_change', 0)}"
    if type_key == "usage":
        return _format_usage(doc.get("total_usage", {}), doc.get("daily_usage_count", 0))
    if type_key == "memory":
        ltm = doc.get("long_term_memory", [])
        return f"长期记忆数: {len(ltm)}"
    if type_key == "context":
        histories = doc.get("history_entries", [])
        return _format_context(histories, pool_size)
    if type_key == "persona":
        return _format_persona(doc.get("persona_attributes", {}))
    if type_key == "blacklist":
        return _format_blacklist(doc.get("block_stats", {}))
    return "未知类型"


def _apply_clear(mongo: MongoDBSystem, query: Dict[str, Any], type_key: str, field: Optional[str], pool_size: int) -> Tuple[int, int]:
    updates: Dict[str, Any] = {}

    if type_key == "context" and field is None:
        docs = mongo.find(query)
        matched = len(docs)
        modified = 0
        for doc in docs:
            hist = doc.get("history_entries", [])
            if not isinstance(hist, list) or not hist:
                continue
            keep = hist[:-pool_size] if pool_size > 0 else hist
            if len(keep) != len(hist):
                update_res = mongo.collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"history_entries": keep, "updated_at": datetime.utcnow().isoformat()}}
                )
                modified += update_res.modified_count
        return matched, modified

    if field:
        if type_key == "usage" and field.startswith("total_usage"):
            updates = {field: 0}
        elif type_key == "blacklist" and field == "block_stats.last_operate_time":
            updates = {field: datetime.utcnow().isoformat()}
        else:
            updates = {field: _get_nested(TYPE_DEFAULTS.get(type_key, {}).get("clear", {}), field) or (0 if "_count" in field or field.endswith("count") else "")}
    else:
        updates = TYPE_DEFAULTS.get(type_key, {}).get("clear", {})

    updates["updated_at"] = datetime.utcnow().isoformat()
    return mongo.update_many(query, updates)


def _apply_set(mongo: MongoDBSystem, query: Dict[str, Any], type_key: str, field: str, value: Any) -> Tuple[int, int]:
    coerced = _validate_set_value(type_key, field, value)
    updates: Dict[str, Any] = {field: coerced, "updated_at": datetime.utcnow().isoformat()}
    if type_key == "favor" and field == "favor_value":
        updates["last_favor_change"] = coerced
    return mongo.update_many(query, updates)


def _apply_rank(mongo: MongoDBSystem, query: Dict[str, Any], type_key: str, field: str, limit: int) -> List[Tuple[str, Any]]:
    """对指定字段进行排序，返回前N个结果

    使用 MongoDB 原生排序功能，避免加载全部数据到内存中排序。
    """
    results = []

    if field == "history_entries":
        # 数组类型：使用聚合管道按数组长度排序
        pipeline = [
            {"$match": query},
            {"$addFields": {"_sort_value": {"$size": "$history_entries"}}},
            {"$sort": {"_sort_value": -1}},
            {"$limit": limit},
            {"$project": {"user_id": 1, "_sort_value": 1}}
        ]
        for doc in mongo.aggregate(pipeline):
            user_id = str(doc.get("user_id", "")).strip()
            results.append((user_id, doc.get("_sort_value", 0)))
    else:
        # 数值类型（包括嵌套字段如 total_usage.total_tokens）
        # MongoDB 原生支持嵌套字段排序，直接在数据库层面完成排序和截断
        for doc in mongo._user_data_collection.find(query).sort(field, -1).limit(limit):
            user_id = str(doc.get("user_id", "")).strip()
            raw_value = _get_nested(doc, field)

            # 处理不同类型的值
            if raw_value is None:
                numeric_value = 0
            elif isinstance(raw_value, (int, float)):
                numeric_value = raw_value
            elif isinstance(raw_value, list):
                # 兼容处理：如果实际数据是数组，使用长度
                numeric_value = len(raw_value)
            else:
                # 字符串类型转换
                try:
                    numeric_value = float(str(raw_value).strip())
                except (ValueError, TypeError):
                    numeric_value = 0

            results.append((user_id, numeric_value))

    return results


# =============================================================================
# Command Executor
# =============================================================================

class CommandExecutor:
    """命令执行器 - 用于本地运行指令系统"""

    def __init__(self, mongo_url: str, bot_id: str, group_id: str,
                 context_pool_size: int = 0,
                 usage_cross_group: bool = False,
                 persona_cross_group: bool = False,
                 favor_cross_group: bool = False,
                 blacklist_cross_group: bool = False):
        self.mongo = MongoDBSystem(mongo_url)
        self.bot_id = bot_id
        self.group_id = group_id
        self.pool_size = context_pool_size
        self.cross_group_map = {
            "usage": usage_cross_group,
            "persona": persona_cross_group,
            "favor": favor_cross_group,
            "blacklist": blacklist_cross_group,
        }

    def execute(self, user_query: str) -> Dict[str, Any]:
        response: Dict[str, Any] = {
            "success": False,
            "result": "",
            "command_type": "",
            "parameters": [],
            "matched_count": 0,
            "modified_count": 0,
            "action": "",
            "type_key": "",
            "field": "",
            "has_any": False,
        }

        action, type_key, field, has_any, params = parse_command(user_query)
        command_label = f"{action}.{type_key}" if type_key else action

        response.update({
            "command_type": command_label,
            "parameters": params,
            "action": action,
            "type_key": type_key or "",
            "field": field or "",
            "has_any": has_any,
        })

        if action not in {"get", "set", "clear", "rank"} or not type_key:
            response["result"] = "指令格式错误"
            return response

        if action == "set" and not field:
            response["result"] = "set指令必须指定精确字段"
            return response

        if action == "rank":
            if not field:
                response["result"] = "rank指令必须指定精确字段"
                return response
            if type_key not in RANK_FIELDS:
                response["result"] = f"rank指令不支持 {type_key} 类型，支持类型: {', '.join(RANK_FIELDS.keys())}"
                return response
            resolved_field = _resolve_rank_field(type_key, field)
            if resolved_field is None:
                response["result"] = f"rank指令不支持 {type_key} 类型的 {field} 字段"
                return response
            field = resolved_field

        self._current_type_key = type_key

        result_lines: List[str] = []
        total_modified = 0
        total_queried = 0

        if action in {"get", "clear"}:
            for param in params:
                query = self._build_query(param, has_any)

                if action == "get":
                    targets: List[Dict[str, Any]] = []
                    if param == "all" or has_any:
                        targets = self.mongo.find(query)
                    else:
                        doc = self.mongo.find_one(query)
                        if doc:
                            targets = [doc]

                    if not targets:
                        result_lines.append(f"[{param}: 用户不存在]")
                        continue

                    for doc in targets:
                        uid = doc.get("user_id", "")
                        val = _extract_value(doc, type_key, field, self.pool_size)
                        result_lines.append(f"[{uid}:\n{val}]")
                        total_queried += 1
                    continue

                matched, modified = _apply_clear(self.mongo, query, type_key, field, self.pool_size)
                total_modified += modified
                result_lines.append(f"[{param}: 清空完成，匹配{matched}，修改{modified}]")

        elif action == "set":
            if has_any:
                if len(params) < 2 or len(params) % 2 != 0:
                    response["result"] = "any模式需要目标和值成对出现"
                    return response
                for idx in range(0, len(params), 2):
                    target = params[idx]
                    value = params[idx + 1]
                    query = self._build_query(target, True)
                    try:
                        matched, modified = _apply_set(self.mongo, query, type_key, field, value)
                    except ValueError as e:
                        response["result"] = str(e)
                        return response
                    total_modified += modified
                    result_lines.append(f"[{target}: 设置完成，匹配{matched}，修改{modified}]")
            else:
                if len(params) % 2 != 0:
                    response["result"] = "参数数量不正确，对象和值必须成对出现"
                    return response
                for idx in range(0, len(params), 2):
                    uid = params[idx]
                    value = params[idx + 1]
                    query = self._build_query(uid, False)
                    try:
                        matched, modified = _apply_set(self.mongo, query, type_key, field, value)
                    except ValueError as e:
                        response["result"] = str(e)
                        return response
                    total_modified += modified
                    result_lines.append(f"[{uid}: 设置完成，匹配{matched}，修改{modified}]")

        elif action == "rank":
            if has_any:
                if len(params) == 0:
                    scope = "%:%:%"
                    limit = 5
                elif len(params) == 1:
                    scope = params[0]
                    limit = 5
                else:
                    scope = params[0]
                    try:
                        limit = int(params[1])
                    except ValueError:
                        response["result"] = f"limit 必须是整数，得到: {params[1]}"
                        return response
                parts = scope.split(":")
                bid, gid, uid = (parts + ["", "", ""])[:3]
                query: Dict[str, Any] = {}
                if bid and bid != "%":
                    query["bot_id"] = bid
                if gid and gid != "%":
                    query["group_id"] = gid
                if uid and uid != "%":
                    query["user_id"] = uid
            else:
                query = {"bot_id": self.bot_id, "group_id": self.group_id}
                if len(params) == 0:
                    limit = 5
                else:
                    try:
                        limit = int(params[0])
                    except ValueError:
                        response["result"] = f"limit 必须是整数，得到: {params[0]}"
                        return response

            limit = max(1, min(30, limit))

            ranked_results = _apply_rank(self.mongo, query, type_key, field, limit)

            if not ranked_results:
                result_lines.append("未找到匹配的记录")
            else:
                for idx, (user_id, value) in enumerate(ranked_results, 1):
                    clean_user_id = str(user_id).strip()
                    clean_value = str(value).strip()
                    result_lines.append(f"第 {idx} 名: 用户 {clean_user_id}, 值: {clean_value}")
                total_queried = len(ranked_results)

        response["success"] = True
        response["result"] = "\n\n".join(result_lines) if result_lines else "无操作"
        response["matched_count"] = total_queried if action in {"get", "rank"} else total_modified
        response["modified_count"] = total_modified

        return response

    def _build_query(self, target: str, has_any: bool) -> Dict[str, Any]:
        if has_any:
            return _build_query(self.bot_id, self.group_id, target, True)

        cross_enabled = self.cross_group_map.get(self._current_type_key, False)

        if target == "all":
            query = {"bot_id": self.bot_id}
            if not cross_enabled:
                query["group_id"] = self.group_id
        else:
            query = {"bot_id": self.bot_id, "user_id": target}
            if not cross_enabled:
                query["group_id"] = self.group_id
        return query

    def close(self):
        self.mongo.close()


# =============================================================================
# UI Functions
# =============================================================================

def print_banner():
    print("=" * 60)
    print(f"{ROZA_BOLD}{ROZA_BLUE}{ROZA_BANNER}{ROZA_RESET}")
    print("=" * 60)
    print()


def print_help():
    print()
    print("=" * 60)
    print(" 指令帮助")
    print("=" * 60)
    print()
    print("基本格式:")
    print("  /Roza.{action}.{type}[.{field}] {target} [{value}]")
    print()
    print("操作 (action):")
    print("  get   - 查询数据")
    print("  set   - 设置字段值")
    print("  clear - 清空数据")
    print("  rank  - 排序查询")
    print()
    print("数据类型 (type):")
    print("  favor    - 好感度")
    print("  usage    - 用量统计")
    print("  memory   - 长期记忆")
    print("  context  - 上下文历史")
    print("  persona  - 用户画像")
    print("  blacklist - 黑名单")
    print()
    print("目标 (target):")
    print("  user_id        - 单个用户 ID")
    print("  all            - 当前群所有用户")
    print()
    print("Any 模式 (跨群操作):")
    print("  使用 .any 后缀，目标格式为 bot_id:group_id:user_id")
    print("  % 表示通配符")
    print()
    print("示例:")
    print("-" * 40)
    print()
    print("# 查询当前群所有用户的好感度")
    print("  /Roza.get.favor all")
    print()
    print("# 查询指定用户的好感度")
    print("  /Roza.get.favor 1234567890")
    print()
    print("# 设置好感度")
    print("  /Roza.set.favor.favor_value 1234567890 100")
    print()
    print("# 清空记忆")
    print("  /Roza.clear.memory all")
    print()
    print("# 排序查询 - 好感度前10名")
    print("  /Roza.rank.favor.favor_value 10")
    print()
    print("# 跨群查询所有用户")
    print("  /Roza.get.favor.any %:%:%")
    print()
    print("=" * 60)
    print()


def print_main_menu():
    print()
    print("=" * 60)
    print(" 主菜单")
    print("=" * 60)
    print()
    print("请选择功能:")
    print("  1. 本地运行指令系统")
    print("  2. 配置文件导入")
    print("  3. 数据库表结构更新")
    print("  0. 退出程序")
    print()


# =============================================================================
# Database Configuration
# =============================================================================

def input_database_config() -> Optional[Dict[str, str]]:
    """输入数据库配置"""
    print()
    print("=" * 60)
    print(" 数据库配置")
    print("=" * 60)
    print()

    while True:
        mongo_url = input("MongoDB URL [默认 mongodb://localhost:27017]: ").strip()
        if not mongo_url:
            mongo_url = "mongodb://localhost:27017"

        print(f"正在连接 {mongo_url} ...")
        try:
            test_client = pymongo.MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
            test_client.list_database_names()
            test_client.close()
            print("连接成功！")
            break
        except Exception as e:
            print(f"连接失败: {e}")
            retry = input("是否重试? (y/n): ").strip().lower()
            if retry != 'y':
                return None

    print()
    db_name = input("数据库名 [默认 roza_database]: ").strip()
    if not db_name:
        db_name = "roza_database"

    return {
        "mongo_url": mongo_url,
        "db_name": db_name,
    }


def input_command_executor_config(db_config: Dict[str, str]) -> Optional[CommandExecutor]:
    """输入本地运行指令系统的配置"""
    print()
    print("=" * 60)
    print(" Bot/Group 配置")
    print("=" * 60)
    print()

    bot_id = input("Bot ID: ").strip()
    if not bot_id:
        print("错误: Bot ID 不能为空")
        return None

    group_id = input("Group ID: ").strip()
    if not group_id:
        print("错误: Group ID 不能为空")
        return None

    pool_size_str = input("上下文池大小 [默认 10]: ").strip()
    try:
        pool_size = int(pool_size_str) if pool_size_str else 10
    except ValueError:
        pool_size = 10

    print()
    print("=" * 60)
    print(" 跨群配置")
    print("=" * 60)
    print()

    cross_favor = input("启用好感度跨群? (y/n) [默认 n]: ").strip().lower() == 'y'
    cross_usage = input("启用量统计跨群? (y/n) [默认 n]: ").strip().lower() == 'y'
    cross_persona = input("启用用户画像跨群? (y/n) [默认 n]: ").strip().lower() == 'y'
    cross_blacklist = input("启用黑名单跨群? (y/n) [默认 n]: ").strip().lower() == 'y'

    print()
    print("=" * 60)
    print(" 配置确认")
    print("=" * 60)
    print()
    print(f"  Bot ID:    {bot_id}")
    print(f"  Group ID:  {group_id}")
    print(f"  池大小:    {pool_size}")
    print(f"  跨群好感:  {'启用' if cross_favor else '禁用'}")
    print(f"  跨群用量:  {'启用' if cross_usage else '禁用'}")
    print(f"  跨群画像:  {'启用' if cross_persona else '禁用'}")
    print(f"  跨群名单:  {'启用' if cross_blacklist else '禁用'}")
    print()

    confirm = input("确认配置? (y/n): ").strip().lower()
    if confirm != 'y':
        return None

    return CommandExecutor(
        mongo_url=db_config["mongo_url"],
        bot_id=bot_id,
        group_id=group_id,
        context_pool_size=pool_size,
        usage_cross_group=cross_usage,
        persona_cross_group=cross_persona,
        favor_cross_group=cross_favor,
        blacklist_cross_group=cross_blacklist,
    )


# =============================================================================
# Mode 1: Local Command System
# =============================================================================

def mode_local_command_system(db_config: Dict[str, str]):
    """功能1：本地运行指令系统"""
    executor = input_command_executor_config(db_config)
    if executor is None:
        return

    bot_id = executor.bot_id
    group_id = executor.group_id
    pool_size = executor.pool_size
    cross_config = executor.cross_group_map

    print()
    print("已连接到数据库，可以开始输入指令。")
    print("输入 'help' 查看指令帮助，'quit' 返回主菜单。")
    print()

    try:
        while True:
            try:
                user_input = input(f"[{bot_id}/{group_id}]> ").strip()
            except EOFError:
                print()
                break

            if not user_input:
                continue

            if user_input.lower() in {"quit", "q", "exit", "退出", "返回"}:
                print("返回主菜单。")
                break

            if user_input.lower() in {"help", "h", "?", "帮助"}:
                print_help()
                continue

            if user_input.lower() in {"config", "配置"}:
                print()
                print("当前配置:")
                print(f"  Bot ID: {bot_id}")
                print(f"  Group ID: {group_id}")
                print(f"  池大小: {pool_size}")
                print(f"  跨群好感:  {'启用' if cross_config['favor'] else '禁用'}")
                print(f"  跨群用量:  {'启用' if cross_config['usage'] else '禁用'}")
                print(f"  跨群画像:  {'启用' if cross_config['persona'] else '禁用'}")
                print(f"  跨群名单:  {'启用' if cross_config['blacklist'] else '禁用'}")
                print()
                continue

            result = executor.execute(user_input)

            print()
            if result.get("success"):
                print(f"✓ 指令: {result.get('command_type', '')}")
            else:
                print(f"✗ 指令: {result.get('command_type', '')}")

            if result.get("has_any"):
                print(f"  模式: Any (通配符查询)")

            print()
            print("结果:")
            print("-" * 50)
            result_text = result.get("result", "")
            if result_text:
                print(result_text)
            else:
                print("(无返回内容)")
            print("-" * 50)

            if result.get("success"):
                count = result.get("matched_count", 0)
                action_cn = {"get": "查询", "set": "修改", "clear": "清空", "rank": "排序"}.get(result.get("action", ""), "操作")
                print(f"  {action_cn}数量: {count}")
            else:
                print(f"  错误: {result.get('result', '')}")

            print()

    except KeyboardInterrupt:
        print("\n\n已中断。")
    finally:
        executor.close()


# =============================================================================
# Mode 2: Config File Import
# =============================================================================

def mode_config_import(db_config: Dict[str, str]):
    """功能2：配置文件导入"""
    print()
    print("=" * 60)
    print(" 配置文件导入")
    print("=" * 60)
    print()

    # 选择类型
    mode_type = ""
    while mode_type not in {"bot", "group"}:
        mode_type = input("选择类型 [bot/group]: ").strip().lower()
        if not mode_type:
            print("请输入 bot 或 group")
            continue
        if mode_type not in {"bot", "group"}:
            print("输入错误，请输入 bot 或 group")

    # 根据类型设置默认集合名
    default_collection = "bot_config" if mode_type == "bot" else "group_config"
    collection_name = input(f"集合名 [默认 {default_collection}]: ").strip()
    if not collection_name:
        collection_name = default_collection

    # 输入目录路径
    dir_path = input(f"{mode_type.capitalize()} 配置目录路径: ").strip()
    if not dir_path:
        print("错误: 目录路径不能为空")
        input("按回车键返回主菜单...")
        return

    config_dir = Path(dir_path).expanduser()
    if not config_dir.is_dir():
        print(f"错误: 目录不存在: {config_dir}")
        input("按回车键返回主菜单...")
        return

    # 连接数据库并执行
    try:
        mongo = MongoDBSystem(db_config["mongo_url"], db_config["db_name"])
        collection = mongo.get_collection(collection_name)

        print(f"扫描 {mode_type} 目录: {config_dir}")
        yaml_files = _collect_yaml_files(config_dir)
        print(f"找到 {len(yaml_files)} 个 YAML 文件")

        if mode_type == "bot":
            units = _sync_files(collection, yaml_files, is_bot=True)
            print(f"Bot 总计写入 {units} 条")
        else:
            units = _sync_files(collection, yaml_files, is_bot=False)
            print(f"Group 总计写入 {units} 条")

        print("导入完成！")

    except Exception as e:
        print(f"错误: {e}")
    finally:
        try:
            mongo.close()
        except:
            pass

    input("按回车键返回主菜单...")


# =============================================================================
# Mode 3: Database Schema Update
# =============================================================================

def mode_schema_update(db_config: Dict[str, str]):
    """功能3：数据库表结构更新"""
    print()
    print("=" * 60)
    print(" 数据库表结构更新")
    print("=" * 60)
    print()
    print("此功能将数据库中的字符串格式字段迁移为数组格式。")
    print("处理字段: overusage_output, error_output, overinput_output")
    print()

    collection_name = input("集合名 [默认 bot_config]: ").strip()
    if not collection_name:
        collection_name = "bot_config"

    confirm = input("确认执行迁移? (y/n): ").strip().lower()
    if confirm != 'y':
        print("已取消。")
        input("按回车键返回主菜单...")
        return

    try:
        mongo = MongoDBSystem(db_config["mongo_url"], db_config["db_name"])
        collection = mongo.get_collection(collection_name)

        print(f"\n开始迁移集合 '{collection_name}' 中的字符串字段为数组格式...")
        count = _migrate_string_to_array(collection)
        print(f"\n迁移完成！共处理 {count} 个文档。")

    except Exception as e:
        print(f"错误: {e}")
    finally:
        try:
            mongo.close()
        except:
            pass

    input("按回车键返回主菜单...")


# =============================================================================
# Main Entry
# =============================================================================

def main():
    print_banner()
    print("欢迎使用 Roza 数据库管理工具！")
    print()

    # 步骤1：数据库配置
    db_config = input_database_config()
    if db_config is None:
        print("退出程序。")
        return

    # 步骤2：主菜单循环
    while True:
        print_main_menu()
        choice = input("输入选项 [0/1/2/3]: ").strip()

        if choice == "0":
            print("再见！")
            break
        elif choice == "1":
            mode_local_command_system(db_config)
        elif choice == "2":
            mode_config_import(db_config)
        elif choice == "3":
            mode_schema_update(db_config)
        else:
            print("无效选项，请重新输入。")


if __name__ == "__main__":
    main()
