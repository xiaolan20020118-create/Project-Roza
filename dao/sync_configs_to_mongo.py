"""Sync bot/group YAML configs into MongoDB (upsert).

Assumptions:
- Preferred YAML is a list of units using explicit keys: "- bot_id: "<id>"\n  group_id: "<id>" ...".
- Legacy "search_key: bot_id:group_id" entries are still parsed for backward compatibility.
- No PyYAML; minimal line-based parsing.
"""
import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pymongo


def _iter_units_with_key(yaml_text: str) -> Iterable[Tuple[str, str, str]]:
    """Yield (bot_id, group_id, block) supporting explicit and legacy formats."""

    # Explicit bot_id/group_id form (preferred)
    explicit_pattern = r'(?:^|\n)-\s*bot_id:\s*"?(?P<bot_id>[^"\n]+)"?\s*\n(?P<body>.*?)(?=\n-\s*(?:bot_id|search_key):|\Z)'
    for m in re.finditer(explicit_pattern, yaml_text, re.DOTALL):
        body = m.group("body").strip()
        group_id = parse_scalar(body, "group_id")
        yield m.group("bot_id").strip(), group_id.strip(), body

    # Legacy search_key form: search_key: "bot:group"
    legacy_pattern = r'(?:^|\n)-\s*search_key:\s*"(?P<search_key>[^"]+)"\s*\n(?P<body>.*?)(?=\n-\s*(?:search_key|bot_id):|\Z)'
    for m in re.finditer(legacy_pattern, yaml_text, re.DOTALL):
        sk = m.group("search_key")
        # Legacy: allow both "bot_id:group_id" and bare "bot_id" forms
        if ":" in sk:
            bot_id, group_id = sk.split(":", 1)
        else:
            bot_id, group_id = sk, ""
        yield bot_id.strip(), group_id.strip(), m.group("body").strip()

    # Fallback: single-document (no leading '-') YAML with bot_id/group_id keys
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


def parse_scalar(block: str, key: str) -> str:
    m = re.search(rf'^\s*{re.escape(key)}:\s*"([^"]*)"\s*$', block, re.MULTILINE)
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
            # Stop when dedented to key level or less
            if indent <= key_indent:
                break
            # Strip common indent (key indent + 2 spaces by YAML convention)
            strip_len = key_indent + 2 if indent >= key_indent + 2 else key_indent
            content_lines.append(content[strip_len:])
        return "\n".join(content_lines).rstrip()
    return ""


def parse_list(block: str, key: str) -> List[str]:
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


def upsert_bot_configs(collection, yaml_text: str):
    for bot_id, group_id, block in _iter_units_with_key(yaml_text):
        if not bot_id:
            continue
        doc: Dict[str, object] = {
            "bot_id": bot_id,
            # 基本信息
            "bot_name": parse_scalar(block, "bot_name"),
            "bot_nickname": parse_scalar(block, "bot_nickname"),
            "llm_model": parse_scalar(block, "llm_model"),
            "basic_info": parse_block_scalar(block, "basic_info"),
            # 表达/思考/回复/工具
            "expression_habits": parse_block_scalar(block, "expression_habits"),
            "think_requirement": parse_block_scalar(block, "think_requirement"),
            "reply_instruction": parse_block_scalar(block, "reply_instruction"),
            "function_call_instruction": parse_block_scalar(block, "function_call_instruction"),
            # 常规输出
            "overusage_output": parse_scalar(block, "overusage_output"),
            "error_output": parse_scalar(block, "error_output"),
            # 管理/默认群/好感度
            "admin_users": parse_list(block, "admin_users"),
            "default_groups": parse_list(block, "default_groups"),
            "favor_prompts": parse_list(block, "favor_prompts"),
            "favor_split_points": [int(x) for x in parse_list(block, "favor_split_points") if str(x).strip().lstrip('-').isdigit()],
        }
        collection.update_one({"bot_id": bot_id}, {"$set": doc}, upsert=True)


def upsert_group_configs(collection, yaml_text: str):
    for bot_id, group_id, block in _iter_units_with_key(yaml_text):
        if not bot_id or not group_id:
            continue
        doc: Dict[str, object] = {
            "bot_id": bot_id,
            "group_id": group_id,
            # 群配置顺序参考 group_eg.yml
            "group_info": parse_scalar(block, "group_info"),
            "operating_mode": parse_scalar(block, "operating_mode"),
            "favor_system": parse_scalar(block, "favor_system"),
            "favor_change_display": parse_scalar(block, "favor_change_display"),
            "favor_cross_group": parse_scalar(block, "favor_cross_group"),
            "persona_system": parse_scalar(block, "persona_system"),
            "persona_cross_group": parse_scalar(block, "persona_cross_group"),
            "usage_limit_system": parse_scalar(block, "usage_limit_system"),
            "usage_limit": parse_scalar(block, "usage_limit"),
            "usage_limit_cross_group": parse_scalar(block, "usage_limit_cross_group"),
            "usage_restrict_admin_users": parse_scalar(block, "usage_restrict_admin_users"),
            "max_input_size": parse_scalar(block, "max_input_size"),
            "memory_system": parse_scalar(block, "memory_system"),
            "memory_retrieval_number": parse_scalar(block, "memory_retrieval_number"),
            "context_system": parse_scalar(block, "context_system"),
            "context_pool_size": parse_scalar(block, "context_pool_size"),
            "commonsense_system": parse_scalar(block, "commonsense_system"),
            "commonsense_cross_group": parse_scalar(block, "commonsense_cross_group"),
            "blacklist_system": parse_scalar(block, "blacklist_system"),
            "warn_count": parse_scalar(block, "warn_count"),
            "warn_lifespan": parse_scalar(block, "warn_lifespan"),
            "block_lifespan": parse_scalar(block, "block_lifespan"),
            "blacklist_cross_group": parse_scalar(block, "blacklist_cross_group"),
            "blacklist_restrict_admin_users": parse_scalar(block, "blacklist_restrict_admin_users"),
            "independent_review_system": parse_scalar(block, "independent_review_system"),
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
                upsert_bot_configs(collection, yaml_text)
            else:
                upsert_group_configs(collection, yaml_text)
            total_units += units
            print(f"[OK] {path.name}: {units} 条")
        except Exception as exc:
            print(f"[ERR] {path}: {exc}")
    return total_units


def interactive_main() -> None:
    print("=== 批量录入 YAML 配置到 MongoDB ===")
    mongo_url = input("Mongo URL (默认 mongodb://localhost:27017): ").strip() or "mongodb://localhost:27017"
    db_name = input("数据库名 (默认 roza_database): ").strip() or "roza_database"
    mode = ""
    while mode not in {"bot", "group"}:
        mode = input("选择录入类型 [bot/group] (默认 bot): ").strip().lower() or "bot"

    bot_collection = input("Bot 集合名 (默认 bot_config): ").strip() or "bot_config"
    group_collection = input("Group 集合名 (默认 group_config): ").strip() or "group_config"

    bot_dir = group_dir = None
    if mode == "bot":
        bot_dir = Path(input("Bot 配置目录路径: ").strip()).expanduser()
    if mode == "group":
        group_dir = Path(input("Group 配置目录路径: ").strip()).expanduser()

    client = pymongo.MongoClient(mongo_url)
    db = client[db_name]

    if bot_dir and mode == "bot":
        print(f"扫描 Bot 目录: {bot_dir}")
        bot_files = _collect_yaml_files(bot_dir)
        print(f"找到 {len(bot_files)} 个 YAML 文件")
        bot_units = _sync_files(db[bot_collection], bot_files, is_bot=True)
        print(f"Bot 总计写入 {bot_units} 条")

    if group_dir and mode == "group":
        print(f"扫描 Group 目录: {group_dir}")
        group_files = _collect_yaml_files(group_dir)
        print(f"找到 {len(group_files)} 个 YAML 文件")
        group_units = _sync_files(db[group_collection], group_files, is_bot=False)
        print(f"Group 总计写入 {group_units} 条")

    print("完成。")


if __name__ == "__main__":
    interactive_main()