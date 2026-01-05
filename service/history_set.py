import pymongo
from datetime import datetime
import json
from typing import Dict, Any, List


class MongoDBSystem:
    """统一的MongoDB系统 - 管理所有数据库操作"""
    
    def __init__(self, mongo_url: str, db_name: str = "roza_database"):
        self.client = pymongo.MongoClient(mongo_url)
        self.db = self.client[db_name]
        self.collection = self.db["user_data"]
        
        # 创建复合索引，确保快速查询
        self.collection.create_index([
            ("bot_id", 1),
            ("group_id", 1), 
            ("user_id", 1)
        ], unique=True)
    
    def get_field(self, bot_id: str, group_id: str, user_id: str, field_name: str) -> Any:
        """提取指定字段"""
        document = self.collection.find_one({
            "bot_id": bot_id,
            "group_id": group_id,
            "user_id": user_id
        })
        
        if document:
            return document.get(field_name)
        return None
    
    def update_field(self, bot_id: str, group_id: str, user_id: str, field_name: str, new_value: Any) -> Any:
        """更新指定字段"""
        result = self.collection.update_one(
            {
                "bot_id": bot_id,
                "group_id": group_id,
                "user_id": user_id
            },
            {
                "$set": {
                    field_name: new_value,
                    "updated_at": datetime.utcnow().isoformat()
                }
            },
            upsert=True
        )
        
        return result


class HistoryUpdater:
    """历史会话更新器 - 核心业务逻辑"""
    
    def __init__(self, mongo_system: MongoDBSystem):
        self.mongo_system = mongo_system
    
    def create_history_entry(self, user_name: str, user_query: str, 
                            output: Dict[str, Any]) -> Dict[str, Any]:
        """
        创建历史会话条目
        
        参数：
        - user_name: 用户名称
        - user_query: 用户查询内容
        - output: 输出字典
        
        返回：
        - 历史会话条目字典
        """
        return {
            "user_name": user_name,
            "user_query": user_query,
            "output": output,
            "created_at": datetime.utcnow().isoformat()
        }
    
    def update_history(self, bot_id: str, group_id: str, user_id: str,
                      history_entry: Dict[str, Any]) -> Dict[str, Any]:
        """
        更新历史会话池
        
        将新的历史条目追加到history_entries数组
        并更新total_histories统计
        
        返回：
        - total_histories: 总历史条目数
        - matched_count: 匹配的文档数
        - modified_count: 修改的文档数
        """
        # 使用$push将新条目追加到history_entries数组
        # 使用$inc将total_histories增加1
        result = self.mongo_system.collection.update_one(
            {
                "bot_id": bot_id,
                "group_id": group_id,
                "user_id": user_id
            },
            {
                "$push": {
                    "history_entries": history_entry
                },
                "$inc": {
                    "history_stats.total_histories": 1
                },
                "$set": {
                    "updated_at": datetime.utcnow().isoformat()
                }
            },
            upsert=True
        )
        
        # 查询更新后的total_histories值
        document = self.mongo_system.collection.find_one({
            "bot_id": bot_id,
            "group_id": group_id,
            "user_id": user_id
        })
        
        # 获取total_histories
        if document and "history_stats" in document:
            total_histories = document["history_stats"].get("total_histories", 1)
        else:
            total_histories = 1
        
        return {
            "total_histories": total_histories,
            "matched_count": result.matched_count,
            "modified_count": result.modified_count
        }


def main(
    output: Dict[str, Any],
    user_name: str,
    user_query: str,
    image_info: Dict[str, Any],
    error_output: str,
    bot_id: str,
    group_id: str,
    user_id: str,
    token_usage: Dict[str, Any],
    MONGO_URL: str
) -> Dict[str, Any]:
    """
    历史会话更新主函数
    
    参数：
    - output: 输出字典
    - user_name: 用户名称
    - user_query: 用户查询内容
    - image_info: 必填，包含图片描述列表的字典，示例 {"image_info": ["描述1", "描述2"]}
    - error_output: 错误输出标识
    - bot_id: 机器人ID
    - group_id: 群组ID
    - user_id: 用户ID
    - token_usage: token使用量字典，包含total_token和prompt_token字段
    - MONGO_URL: MongoDB连接URL
    
    返回：
    - total_histories: 总历史条目数
    - history_entry: 本次创建的历史条目
    - matched_count: 匹配的文档数量
    - modified_count: 修改的文档数量
    """
    
    # 检查output是否为错误输出，避免记录错误结果
    # 假设error_output是一个字符串，而output是字典
    # 如果output中包含错误标识，跳过更新
    if isinstance(output, dict) and output.get("error") == error_output:
        return {
            "total_histories": 0,
            "history_entry": "{}",
            "matched_count": 0,
            "modified_count": 0,
            # 添加token统计字段
            "total_chat_count": 0,
            "total_tokens": 0,
            "total_prompt_token": 0,
            "total_output_token": 0
        }
    
    # 初始化系统
    mongo_system = MongoDBSystem(MONGO_URL)
    history_updater = HistoryUpdater(mongo_system)

    # 如果有图片描述列表，按指定格式附加在用户文本后
    user_query_record = user_query
    desc_list: List[str] = []
    if isinstance(image_info, dict):
        raw_list = image_info.get("image_info")
        if isinstance(raw_list, list):
            desc_list = [str(item) for item in raw_list]
    elif isinstance(image_info, list):
        desc_list = [str(item) for item in image_info]

    if desc_list:
        count = len(desc_list)
        parts = " ".join([f"第{i + 1}张:{desc}" for i, desc in enumerate(desc_list)])
        user_query_record = f"{user_query}[用户发送了{count}张图片，{parts}]"
    
    # 创建历史条目
    history_entry = history_updater.create_history_entry(
        user_name=user_name,
        user_query=user_query_record,
        output=output
    )
    
    # 更新历史会话池
    update_result = history_updater.update_history(
        bot_id=bot_id,
        group_id=group_id,
        user_id=user_id,
        history_entry=history_entry
    )
    
    # 提取token使用量并更新total_usage统计
    new_total_usage = {
        "total_chat_count": 0,
        "total_tokens": 0,
        "total_prompt_token": 0,
        "total_output_token": 0
    }
    
    try:
        # 从token_usage提取字段（注意字段名是复数形式）
        total_tokens = token_usage.get("total_tokens", 0) if isinstance(token_usage, dict) else 0
        prompt_tokens = token_usage.get("prompt_tokens", 0) if isinstance(token_usage, dict) else 0
        completion_tokens = token_usage.get("completion_tokens", 0) if isinstance(token_usage, dict) else 0
        
        # 获取当前的total_usage
        current_total_usage = mongo_system.get_field(bot_id, group_id, user_id, "total_usage")
        
        # 确保total_usage是字典类型
        if not isinstance(current_total_usage, dict):
            current_total_usage = {
                "total_chat_count": 0,
                "total_tokens": 0,
                "total_prompt_token": 0,
                "total_output_token": 0
            }
        
        # 更新统计
        new_total_usage = {
            "total_chat_count": current_total_usage.get("total_chat_count", 0) + 1,
            "total_tokens": current_total_usage.get("total_tokens", 0) + total_tokens,
            "total_prompt_token": current_total_usage.get("total_prompt_token", 0) + prompt_tokens,
            "total_output_token": current_total_usage.get("total_output_token", 0) + completion_tokens
        }
        
        # 更新数据库
        mongo_system.update_field(bot_id, group_id, user_id, "total_usage", new_total_usage)
        
    except Exception as e:
        # 如果token统计更新失败，不影响历史记录的保存
        print(f"Warning: Failed to update token usage statistics: {e}")
    
    # 返回结果（将history_entry转换为JSON字符串，并包含total_usage的四个字段）
    return {
        "total_histories": update_result["total_histories"],
        "history_entry": json.dumps(history_entry, ensure_ascii=False),
        "matched_count": update_result["matched_count"],
        "modified_count": update_result["modified_count"],
        # 返回total_usage的四个字段
        "total_chat_count": new_total_usage["total_chat_count"],
        "total_tokens": new_total_usage["total_tokens"],
        "total_prompt_token": new_total_usage["total_prompt_token"],
        "total_output_token": new_total_usage["total_output_token"]
    }
