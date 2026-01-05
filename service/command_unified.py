import re
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pymongo


class MongoDBSystem:
    """Lightweight MongoDB helper for command operations."""

    def __init__(self, mongo_url: str, db_name: str = "roza_database"):
        self.client = pymongo.MongoClient(mongo_url)
        self.db = self.client[db_name]
        self.collection = self.db["user_data"]

    def find(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        return list(self.collection.find(query))

    def find_one(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self.collection.find_one(query)

    def update_many(self, query: Dict[str, Any], updates: Dict[str, Any]) -> Tuple[int, int]:
        result = self.collection.update_many(query, {"$set": updates})
        return result.matched_count, result.modified_count

    def update_one(self, query: Dict[str, Any], updates: Dict[str, Any]) -> Tuple[int, int]:
        result = self.collection.update_one(query, {"$set": updates})
        return result.matched_count, result.modified_count


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
    # segments example: ["Roza", "set", "usage", "total_tokens", "any"]
    if len(segments) < 3 or segments[0] != "Roza":
        return "", "", None, False, []

    action = segments[1]
    type_key = segments[2]
    field = None
    has_any = False

    if len(segments) == 4:
        if segments[3] == "any":
            has_any = True
        else:
            field = segments[3]
    elif len(segments) >= 5:
        field = segments[3] if segments[3] != "any" else None
        has_any = segments[4] == "any"

    # allow trailing .any without params
    if not params and has_any:
        params = ["%:%:%"]

    # default to all when no params and no any
    if not params and not has_any:
        params = ["all"]

    return action, type_key, field, has_any, params


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
        # default clear only resets daily counter; totals require precise fields
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


def _get_nested(doc: Dict[str, Any], dotted: str) -> Any:
    parts = dotted.split(".")
    cur: Any = doc
    for part in parts:
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _set_nested(doc: Dict[str, Any], dotted: str, value: Any) -> Dict[str, Any]:
    parts = dotted.split(".")
    cur = doc
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value
    return doc


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

    # any mode accepts wildcard %
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
        raise ValueError("block_status必须是布尔值")
    # everything else stringified
    return str(value)


def _log_entry(command_type: str, modified: int, target: str, result: str) -> str:
    return (
        f"指令类型：{command_type}\n"
        f"操作计数：{modified}\n"
        f"指向对象：{target}\n"
        f"执行结果：{result}\n\n"
    )


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


def _apply_clear(mongo: MongoDBSystem, query: Dict[str, Any], type_key: str, field: Optional[str]) -> Tuple[int, int]:
    updates: Dict[str, Any] = {}
    if field:
        # precise clear
        if type_key == "usage" and field.startswith("total_usage"):
            # allow clearing totals only when precise
            updates = {field: 0}
        elif type_key == "blacklist" and field == "block_stats.last_operate_time":
            updates = {field: datetime.utcnow().isoformat()}
        else:
            updates = {field: _get_nested(TYPE_DEFAULTS.get(type_key, {}).get("clear", {}), field) or (0 if "_count" in field or field.endswith("count") else "")}
    else:
        # type-level clear
        updates = TYPE_DEFAULTS.get(type_key, {}).get("clear", {})
    updates["updated_at"] = datetime.utcnow().isoformat()
    return mongo.update_many(query, updates)


def _apply_set(mongo: MongoDBSystem, query: Dict[str, Any], type_key: str, field: str, value: Any) -> Tuple[int, int]:
    try:
        coerced = _validate_set_value(type_key, field, value)
    except ValueError:
        raise

    updates: Dict[str, Any] = {field: coerced, "updated_at": datetime.utcnow().isoformat()}
    # for favor_value also mirror last_favor_change when setting explicitly
    if type_key == "favor" and field == "favor_value":
        updates["last_favor_change"] = coerced
    return mongo.update_many(query, updates)


def execute_command(
    user_query: str,
    bot_id: str,
    group_id: str,
    is_user_admin: str,
    context_pool_size: int,
    mongo_url: str,
    usage_limit_cross_group: str = "disable",
    persona_cross_group: str = "disable",
    favor_cross_group: str = "disable",
    blacklist_cross_group: str = "disable",
) -> Dict[str, Any]:
    """Unified command entry point."""
    response: Dict[str, Any] = {
        "result": "",
        "command_type": "",
        "parameters": [],
        "modified_count": 0,
        "logs": [],
        "action": "",
        "type_key": "",
        "field": "",
        "has_any": False,
    }

    if is_user_admin != "true":
        response["result"] = "无管理员权限，无法执行此操作"
        return response

    try:
        pool_size = int(context_pool_size)
    except (TypeError, ValueError):
        pool_size = 0

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

    if action not in {"get", "set", "clear"} or not type_key:
        response["result"] = "指令格式错误"
        return response

    if action == "set" and not field:
        response["result"] = "set指令必须指定精确字段"
        return response

    mongo = MongoDBSystem(mongo_url)

    result_lines: List[str] = []
    logs: List[str] = []
    total_modified = 0
    total_queried = 0

    cross_group_map = {
        "usage": usage_limit_cross_group,
        "persona": persona_cross_group,
        "favor": favor_cross_group,
        "blacklist": blacklist_cross_group,
    }

    if action in {"get", "clear"}:
        for param in params:
            query = _build_query(bot_id, group_id, param, has_any)
            targets: List[Dict[str, Any]] = []

            if action == "get":
                if param == "all" or has_any:
                    targets = mongo.find(query)
                else:
                    doc = mongo.find_one(query)
                    if doc:
                        targets = [doc]
                if not targets:
                    result_lines.append(f"[{param}: 用户不存在]")
                    logs.append(_log_entry(command_label, 0, param, "not found"))
                    continue
                for doc in targets:
                    uid = doc.get("user_id", "")
                    val = _extract_value(doc, type_key, field, pool_size)
                    result_lines.append(f"[{uid}:\n{val}]")
                    logs.append(_log_entry(command_label, 1, uid or param, "ok"))
                    total_queried += 1
                continue

            # clear branch
            if has_any:
                # any mode: use wildcard query from _build_query
                pass  # query already built
            else:
                # normal mode: apply cross-group logic
                cross_enabled = cross_group_map.get(type_key, "disable") == "enable"
                if param == "all":
                    query = {"bot_id": bot_id}
                    if not cross_enabled:
                        query["group_id"] = group_id
                else:
                    query = {"bot_id": bot_id, "user_id": param}
                    if not cross_enabled:
                        query["group_id"] = group_id

            if type_key == "context" and field is None:
                # 删除最新 context_pool_size 条历史记录而非清空
                docs = mongo.find(query)
                matched = len(docs)
                modified = 0
                for doc in docs:
                    hist = doc.get("history_entries", [])
                    if not isinstance(hist, list) or not hist:
                        continue
                    keep = hist[:-pool_size] if pool_size > 0 else hist
                    if len(keep) != len(hist):
                        update_res = mongo.collection.update_one({"_id": doc["_id"]}, {"$set": {"history_entries": keep, "updated_at": datetime.utcnow().isoformat()}})
                        modified += update_res.modified_count
                total_modified += modified
            else:
                matched, modified = _apply_clear(mongo, query, type_key, field)
                total_modified += modified

            target_label = param
            result_lines.append(f"[{target_label}: 清空完成，匹配{matched}，修改{modified}]")
            logs.append(_log_entry(command_label, modified, target_label, "ok" if matched else "not found"))

    else:  # set
        if has_any:
            if len(params) < 2 or len(params) % 2 != 0:
                response.update({"result": "any模式需要目标和值成对出现", "logs": logs})
                return response
            for idx in range(0, len(params), 2):
                target = params[idx]
                value = params[idx + 1]
                query = _build_query(bot_id, group_id, target, True)
                try:
                    matched, modified = _apply_set(mongo, query, type_key, field, value)
                except ValueError as e:
                    response.update({"result": str(e), "modified_count": total_modified, "logs": logs})
                    return response
                total_modified += modified
                result_lines.append(f"[{target}: 设置完成，匹配{matched}，修改{modified}]")
                logs.append(_log_entry(command_label, modified, target, "ok" if matched else "not found"))
        else:
            if len(params) % 2 != 0:
                response.update({"result": "参数数量不正确，对象和值必须成对出现", "logs": logs})
                return response
            for idx in range(0, len(params), 2):
                uid = params[idx]
                value = params[idx + 1]
                cross_enabled = cross_group_map.get(type_key, "disable") == "enable"
                if uid == "all":
                    query = {"bot_id": bot_id}
                    if not cross_enabled:
                        query["group_id"] = group_id
                else:
                    query = {"bot_id": bot_id, "user_id": uid}
                    if not cross_enabled:
                        query["group_id"] = group_id
                try:
                    matched, modified = _apply_set(mongo, query, type_key, field, value)
                except ValueError as e:
                    response.update({"result": str(e), "modified_count": total_modified, "logs": logs})
                    return response
                total_modified += modified
                result_lines.append(f"[{uid}: 设置完成，匹配{matched}，修改{modified}]")
                logs.append(_log_entry(command_label, modified, uid, "ok" if matched else "not found"))

    response.update({
        "result": "\n\n".join(result_lines) if result_lines else "无操作",
        "modified_count": total_queried if action == "get" else total_modified,
        "logs": logs,
    })
    return response


def main(
    user_query: str,
    bot_id: str,
    group_id: str,
    is_user_admin: str,
    context_pool_size: int,
    mongo_url: str,
    usage_limit_cross_group: str = "disable",
    persona_cross_group: str = "disable",
    favor_cross_group: str = "disable",
    blacklist_cross_group: str = "disable",
) -> Dict[str, Any]:
    """Thin wrapper to comply with main entry requirement."""
    resp = execute_command(
        user_query=user_query,
        bot_id=bot_id,
        group_id=group_id,
        is_user_admin=is_user_admin,
        context_pool_size=context_pool_size,
        mongo_url=mongo_url,
        usage_limit_cross_group=usage_limit_cross_group,
        persona_cross_group=persona_cross_group,
        favor_cross_group=favor_cross_group,
        blacklist_cross_group=blacklist_cross_group,
    )

    # Explicit flat output for downstream consumption
    return {
        "result": resp.get("result", ""),
        "command_type": resp.get("command_type", ""),
        "parameters": resp.get("parameters", []),
        "modified_count": resp.get("modified_count", 0),
        "logs": resp.get("logs", []),
        "action": resp.get("action", ""),
        "type_key": resp.get("type_key", ""),
        "field": resp.get("field", ""),
        "has_any": resp.get("has_any", False),
    }
