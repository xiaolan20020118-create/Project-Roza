import pymongo
from datetime import datetime
import re
import json
import math
import random
from collections import Counter
from typing import Dict, Any, Optional, Tuple, List


class MongoDBSystem:
    """统一的MongoDB系统 - 管理所有数据库操作"""

    # 模板文档的group_id常量
    TEMPLATE_GROUP_ID = "9999"

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

        # 跨群配置（默认值）
        self._favor_cross_group = "disable"
        self._persona_cross_group = "disable"
        self._blacklist_cross_group = "disable"
        self._usage_limit_cross_group = "disable"

    def set_cross_group_config(self, favor_cross_group: str = "disable",
                               persona_cross_group: str = "disable",
                               blacklist_cross_group: str = "disable",
                               usage_limit_cross_group: str = "disable"):
        """
        设置跨群配置参数

        参数：
            favor_cross_group: 好感度是否跨群
            persona_cross_group: 用户画像是否跨群
            blacklist_cross_group: 黑名单是否跨群
            usage_limit_cross_group: 用量统计是否跨群
        """
        self._favor_cross_group = favor_cross_group
        self._persona_cross_group = persona_cross_group
        self._blacklist_cross_group = blacklist_cross_group
        self._usage_limit_cross_group = usage_limit_cross_group

    def _get_default_persona_attributes(self) -> Dict[str, str]:
        """获取默认的用户画像属性"""
        return {
            "basic_info": "",
            "living_habits": "",
            "psychological_traits": "",
            "interests_preferences": "",
            "dislikes": "",
            "ai_expectations": "",
            "memory_points": "",
        }

    def _get_default_block_stats(self) -> Dict[str, Any]:
        """获取默认的黑名单状态"""
        current_time = datetime.utcnow()
        return {
            "block_status": True,  # True=pass, False=block
            "block_count": 0,
            "last_operate_time": current_time.isoformat()
        }

    def _get_default_total_usage(self) -> Dict[str, int]:
        """获取默认的总使用量统计"""
        return {
            "total_chat_count": 0,
            "total_tokens": 0,
            "total_prompt_token": 0,
            "total_output_token": 0
        }

    def get_document(self, bot_id: str, group_id: str, user_id: str) -> Dict[str, Any]:
        """
        获取用户文档，如果不存在则创建默认文档

        新逻辑：当用户首次进入新群组时，根据跨群配置决定是否从9999模板继承数据
        跨群配置通过set_cross_group_config()方法设置

        参数：
            bot_id: 机器人ID
            group_id: 群组ID
            user_id: 用户ID

        返回：用户文档字典
        """
        # 步骤1：尝试读取当前群组文档
        document = self.collection.find_one({
            "bot_id": bot_id,
            "group_id": group_id,
            "user_id": user_id
        })

        # 如果文档存在，直接返回
        if document:
            return document

        # 步骤2：文档不存在，查询9999模板和其他群组文档
        current_time = datetime.utcnow()

        # 查询9999模板文档
        template_doc = self.collection.find_one({
            "bot_id": bot_id,
            "group_id": self.TEMPLATE_GROUP_ID,
            "user_id": user_id
        })

        # 查询其他群组的文档（排除9999和当前群组）
        other_group_docs = list(self.collection.find({
            "bot_id": bot_id,
            "user_id": user_id,
            "group_id": {"$nin": [self.TEMPLATE_GROUP_ID, group_id]}
        }).limit(1))

        # 步骤3：判断场景并决定继承策略
        # 场景A：9999模板存在 → 从9999继承
        # 场景B：9999不存在，但有其他群组文档 → 从其他群组创建9999，再从9999继承
        # 场景C：9999和其他群组都不存在 → 创建全新文档

        has_template = template_doc is not None
        has_other_group = len(other_group_docs) > 0

        if not has_template and has_other_group:
            # 场景B：从其他群组创建9999模板
            source_doc = other_group_docs[0]
            template_doc = self._create_template_from_source(bot_id, user_id, source_doc, current_time)

        # 步骤4：构建新文档（根据跨群配置决定继承哪些字段）
        new_doc = self._build_document_from_template(
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            template_doc=template_doc,
            current_time=current_time
        )

        # 步骤5：插入新文档并重新读取
        self.collection.insert_one(new_doc)

        # 重新读取并返回
        document = self.collection.find_one({
            "bot_id": bot_id,
            "group_id": group_id,
            "user_id": user_id
        })

        return document if document else new_doc

    def _create_template_from_source(self, bot_id: str, user_id: str,
                                      source_doc: Dict[str, Any],
                                      current_time: datetime) -> Dict[str, Any]:
        """
        从源文档创建9999模板文档

        参数：
            bot_id: 机器人ID
            user_id: 用户ID
            source_doc: 源群组文档
            current_time: 当前时间

        返回：创建的9999模板文档
        """
        template_doc = {
            "bot_id": bot_id,
            "group_id": self.TEMPLATE_GROUP_ID,
            "user_id": user_id,
            # 从源文档继承跨群字段
            # favor相关
            "favor_value": source_doc.get("favor_value", 0),
            "last_favor_change": source_doc.get("last_favor_change", 0),
            # persona相关
            "persona_attributes": source_doc.get("persona_attributes", self._get_default_persona_attributes()),
            # blacklist相关
            "block_stats": source_doc.get("block_stats", self._get_default_block_stats()),
            # usage相关（只继承daily_usage_count，total_usage各群独立不继承）
            "daily_usage_count": source_doc.get("daily_usage_count", 0),
            # 不继承或使用默认值的字段
            "total_usage": self._get_default_total_usage(),  # 各群独立，9999模板使用默认值
            "long_term_memory": source_doc.get("long_term_memory", []),
            "history_entries": [],
            "history_stats": {"total_histories": 0},
            # 时间戳
            "created_at": current_time.isoformat(),
            "updated_at": current_time.isoformat(),
        }

        # 插入9999模板文档
        self.collection.insert_one(template_doc)

        return template_doc

    def _build_document_from_template(self, bot_id: str, group_id: str, user_id: str,
                                       template_doc: Optional[Dict[str, Any]],
                                       current_time: datetime) -> Dict[str, Any]:
        """
        根据模板文档和跨群配置构建新文档

        参数：
            bot_id: 机器人ID
            group_id: 群组ID
            user_id: 用户ID
            template_doc: 9999模板文档（可能为None）
            current_time: 当前时间

        返回：构建的新文档
        """
        # 从模板继承或使用默认值的辅助函数
        def get_value(field_name: str, default_value: Any, cross_group_enabled: str) -> Any:
            if template_doc and cross_group_enabled == "enable":
                return template_doc.get(field_name, default_value)
            return default_value

        # 构建新文档
        new_doc = {
            "bot_id": bot_id,
            "group_id": group_id,
            "user_id": user_id,

            # blacklist相关字段（受blacklist_cross_group影响）
            "block_stats": get_value("block_stats", self._get_default_block_stats(), self._blacklist_cross_group),

            # favor相关字段（受favor_cross_group影响）
            "favor_value": get_value("favor_value", 0, self._favor_cross_group),
            "last_favor_change": get_value("last_favor_change", 0, self._favor_cross_group),

            # persona相关字段（受persona_cross_group影响）
            "persona_attributes": get_value("persona_attributes", self._get_default_persona_attributes(), self._persona_cross_group),

            # usage相关字段
            # daily_usage_count受usage_limit_cross_group影响
            "daily_usage_count": get_value("daily_usage_count", 0, self._usage_limit_cross_group),

            # total_usage各群独立，不继承
            "total_usage": self._get_default_total_usage(),

            # 非跨群字段（各群独立）
            "long_term_memory": [],
            "history_entries": [],
            "history_stats": {"total_histories": 0},

            # 系统字段
            "created_at": current_time.isoformat(),
            "updated_at": current_time.isoformat(),
        }

        return new_doc
    
    def update_document(self, bot_id: str, group_id: str, user_id: str, 
                       updates: Dict[str, Any]) -> Any:
        """更新用户文档"""
        updates["updated_at"] = datetime.utcnow().isoformat()
        
        result = self.collection.update_one(
            {
                "bot_id": bot_id,
                "group_id": group_id,
                "user_id": user_id
            },
            {
                "$set": updates
            },
            upsert=True
        )
        
        return result
    
    def get_field(self, bot_id: str, group_id: str, user_id: str, 
                  field_name: str) -> Any:
        """提取指定字段"""
        document = self.get_document(bot_id, group_id, user_id)
        return document.get(field_name)
    
    def update_field(self, bot_id: str, group_id: str, user_id: str, 
                    field_name: str, new_value: Any) -> Any:
        """更新指定字段"""
        updates = {field_name: new_value}
        return self.update_document(bot_id, group_id, user_id, updates)
    
    def process_and_update_field(self, bot_id: str, group_id: str, user_id: str,
                                field_name: str, process_function) -> Dict[str, Any]:
        """通用字段处理函数：提取→处理→更新"""
        current_value = self.get_field(bot_id, group_id, user_id, field_name)
        processed_value = process_function(current_value)
        result = self.update_field(bot_id, group_id, user_id, field_name, processed_value)

        return {
            "original_value": current_value,
            "processed_value": processed_value,
            "update_status": "success" if result.acknowledged else "failed",
            "matched_count": result.matched_count,
            "modified_count": result.modified_count
        }

    def get_full_document_schema(self) -> Dict[str, Any]:
        """
        获取完整的用户数据文档结构定义（仅用于参考，不影响实际功能）

        字段对应关系：
        - favor: favor_value + last_favor_change（受favor_cross_group影响）
        - usage: total_usage字典（4个字段，各群独立）+ daily_usage_count（受usage_limit_cross_group影响）
        - memory: long_term_memory（各群独立）
        - context: history_entries前N条（各群独立）
        - persona: persona_attributes全部字段（受persona_cross_group影响）
        - blacklist: block_stats全部字段（受blacklist_cross_group影响）

        表结构字段对应关系：
        - bot_id: 机器人ID（索引字段）
        - group_id: 群组ID（索引字段，9999为跨群模板）
        - user_id: 用户ID（索引字段）

        跨群字段（存储在9999模板中）：
        - favor相关（受favor_cross_group影响）：
          ├─ favor_value: 好感度值（整数）
          └─ last_favor_change: 最后一次好感度变化量（整数）
        - persona相关（受persona_cross_group影响）：
          └─ persona_attributes: 用户画像属性（字典）
              ├─ basic_info: 基本信息
              ├─ living_habits: 生活习惯
              ├─ psychological_traits: 心理特征
              ├─ interests_preferences: 兴趣偏好
              ├─ dislikes: 反感点
              ├─ ai_expectations: 对AI的期望
              └─ memory_points: 希望记住的信息
        - blacklist相关（受blacklist_cross_group影响）：
          └─ block_stats: 黑名单状态（字典）
              ├─ block_status: 封禁状态（True=pass, False=block）
              ├─ block_count: 违规计数（整数）
              └─ last_operate_time: 最后操作时间（ISO格式字符串）
        - usage相关中受usage_limit_cross_group影响的字段：
          └─ daily_usage_count: 每日使用量计数（整数，每日重置）

        非跨群字段（每个群组独立）：
        - memory相关：
          └─ long_term_memory: 长期记忆数组（数组）
        - context相关：
          ├─ history_entries: 历史对话记录数组（数组）
          └─ history_stats: 历史统计（字典）
              └─ total_histories: 总历史条目数（整数）
        - usage相关中各群独立的字段：
          └─ total_usage: 总使用量统计（字典）
              ├─ total_chat_count: 总对话次数（整数）
              ├─ total_tokens: 总token数（整数）
              ├─ total_prompt_token: 总输入token数（整数）
              └─ total_output_token: 总输出token数（整数）

        系统字段：
        - created_at: 创建时间（ISO格式字符串）
        - updated_at: 更新时间（ISO格式字符串）

        返回：表结构定义字典
        """
        current_time = datetime.utcnow()
        return {
            # 索引字段
            "bot_id": "机器人ID（字符串）",
            "group_id": "群组ID（字符串），9999为跨群模板文档",
            "user_id": "用户ID（字符串）",

            # favor相关（受favor_cross_group影响）
            "favor_value": "好感度值（整数，默认0）",
            "last_favor_change": "最后一次好感度变化量（整数，默认0）",

            # persona相关（受persona_cross_group影响）
            "persona_attributes": {
                "basic_info": "基本信息（字符串，默认空）",
                "living_habits": "生活习惯（字符串，默认空）",
                "psychological_traits": "心理特征（字符串，默认空）",
                "interests_preferences": "兴趣偏好（字符串，默认空）",
                "dislikes": "反感点（字符串，默认空）",
                "ai_expectations": "对AI的期望（字符串，默认空）",
                "memory_points": "希望记住的信息（字符串，默认空）",
            },

            # blacklist相关（受blacklist_cross_group影响）
            "block_stats": {
                "block_status": "封禁状态（布尔，True=pass, False=block，默认True）",
                "block_count": "违规计数（整数，默认0）",
                "last_operate_time": f"最后操作时间（ISO格式字符串，示例：{current_time.isoformat()}）",
            },

            # usage相关（部分受usage_limit_cross_group影响）
            "daily_usage_count": "每日使用量计数（整数，默认0，每日重置，受usage_limit_cross_group影响）",
            "total_usage": {
                "total_chat_count": "总对话次数（整数，默认0，各群独立）",
                "total_tokens": "总token数（整数，默认0，各群独立）",
                "total_prompt_token": "总输入token数（整数，默认0，各群独立）",
                "total_output_token": "总输出token数（整数，默认0，各群独立）",
            },

            # 非跨群字段（各群独立）
            "long_term_memory": "长期记忆数组（数组，默认空）",
            "history_entries": "历史对话记录数组（数组，默认空）",
            "history_stats": {
                "total_histories": "总历史条目数（整数，默认0）",
            },

            # 系统字段
            "created_at": f"创建时间（ISO格式字符串，示例：{current_time.isoformat()}）",
            "updated_at": f"更新时间（ISO格式字符串，示例：{current_time.isoformat()}）",
        }


class UtilityFunctions:
    """通用工具函数类"""
    
    @staticmethod
    def random_message(messages: Any) -> str:
        """从消息数组中随机选择一条消息，如果不是数组则返回字符串本身"""
        if isinstance(messages, list):
            if not messages:
                return ""
            return random.choice(messages)
        return str(messages) if messages else ""

    @staticmethod
    def ensure_json_serializable(obj: Any) -> Any:
        """确保对象是JSON可序列化的"""
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, dict):
            return {k: UtilityFunctions.ensure_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [UtilityFunctions.ensure_json_serializable(item) for item in obj]
        elif isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj
        else:
            return str(obj)
    
    @staticmethod
    def dict_to_json_string(obj: Any) -> str:
        """将字典对象转换为JSON字符串"""
        if isinstance(obj, dict):
            serializable_obj = UtilityFunctions.ensure_json_serializable(obj)
            return json.dumps(serializable_obj, ensure_ascii=False)
        elif isinstance(obj, str):
            return obj
        else:
            return str(obj)
    
    @staticmethod
    def safe_int_convert(value: Any, default: int = 0) -> int:
        """安全转换为整数"""
        try:
            if value is None:
                return default
            if isinstance(value, str) and not value.strip():
                return default
            return int(str(value).strip())
        except (ValueError, TypeError, AttributeError):
            return default


class BlacklistManager:
    """黑名单管理器 - 核心业务逻辑"""
    
    def __init__(self, mongo_system: MongoDBSystem):
        self.mongo_system = mongo_system
    
    def check_blacklist_status(self, bot_id: str, group_id: str, user_id: str,
                              warn_lifespan: int, block_lifespan: int,
                              timestamp: float) -> Dict[str, Any]:
        """
        检查用户当前屏蔽状态
        新逻辑：
        - block_status: True=pass(允许), False=block(封锁)
        - block_count: 违规计数
        - last_operate_time: 最后操作时间
        
        返回：是否允许继续、停止消息、状态信息
        """
        # 获取当前用户的block_stats
        block_stats = self.mongo_system.get_field(bot_id, group_id, user_id, "block_stats")
        
        if not isinstance(block_stats, dict):
            block_stats = {
                "block_status": True,
                "block_count": 0,
                "last_operate_time": datetime.utcnow().isoformat()
            }
        
        block_status = block_stats.get("block_status", True)
        block_count = block_stats.get("block_count", 0)
        last_operate_time_str = block_stats.get("last_operate_time", datetime.utcnow().isoformat())
        
        # 解析last_operate_time
        try:
            last_operate_dt = datetime.fromisoformat(last_operate_time_str.replace('Z', '+00:00'))
            last_operate_timestamp = last_operate_dt.timestamp()
        except (ValueError, AttributeError):
            last_operate_timestamp = timestamp
        
        # 计算时间差
        delta_time = timestamp - last_operate_timestamp
        
        # 初始化返回值
        allow_continue = True
        stop_message = " "
        need_update = False
        
        # 核心业务逻辑
        if block_status is True:  # pass状态
            if block_count == 0:
                # 直接进入下一步
                allow_continue = True
            else:  # block_count > 0
                if delta_time >= warn_lifespan:
                    # 时间差大于warn_lifespan，重置block_count
                    block_stats["block_count"] = 0
                    # 不更新last_operate_time
                    need_update = True
                    allow_continue = True
                else:
                    # 时间差不大于warn_lifespan，不做任何修改
                    allow_continue = True
                    
        else:  # block_status is False, block状态
            if delta_time >= block_lifespan:
                # 时间差大于block_lifespan，允许对话
                block_stats["block_status"] = True
                # 不更新last_operate_time
                need_update = True
                allow_continue = True
            else:
                # 时间差不大于block_lifespan，不允许对话
                allow_continue = False
                # 计算剩余封锁时间
                left_block_time = int(block_lifespan - delta_time)
                stop_message = f"不想理你，{left_block_time}秒后再来吧"
        
        # 更新数据库
        if need_update:
            update_result = self.mongo_system.update_field(
                bot_id, group_id, user_id, "block_stats", block_stats
            )
            matched_count = update_result.matched_count
            modified_count = update_result.modified_count
        else:
            # 模拟一个成功的结果
            matched_count = 1
            modified_count = 0
        
        return {
            "allow_continue": allow_continue,
            "stop_message": stop_message,
            "block_status": block_status,  # 返回当前状态：True=pass, False=block
            "matched_count": matched_count,
            "modified_count": modified_count
        }


class UsageLimitManager:
    """用量限制管理器 - 核心业务逻辑"""
    
    def __init__(self, mongo_system: MongoDBSystem):
        self.mongo_system = mongo_system
        self.util = UtilityFunctions()
    
    def format_date(self, year: str, month: str, day: str) -> str:
        """格式化日期为YYYYMMDD格式"""
        try:
            year_str = str(year).zfill(4) if year else "1970"
            month_str = str(month).zfill(2) if month else "01"
            day_str = str(day).zfill(2) if day else "01"
            
            date_str = f"{year_str}{month_str}{day_str}"
            if len(date_str) == 8 and date_str.isdigit():
                return date_str
            else:
                return "19700101"
        except (ValueError, TypeError):
            return "19700101"
    
    def check_usage_limit(self, bot_id: str, group_id: str, user_id: str,
                         usage_limit: int, year: str, month: str, day: str,
                         overusage_output: Any) -> Dict[str, Any]:
        """
        检查用户当前用量限制状态
        使用updated_at字段判断是否跨天，不再单独维护last_request_date
        返回：是否允许继续、停止消息、用量信息
        overusage_output可以是字符串或字符串数组
        """
        # 获取当前用户的用量数据和最后更新时间
        current_usage = self.mongo_system.get_field(bot_id, group_id, user_id, "daily_usage_count")
        updated_at_str = self.mongo_system.get_field(bot_id, group_id, user_id, "updated_at")
        
        # 安全转换数值
        current_usage_val = self.util.safe_int_convert(current_usage, 0)
        
        # 格式化当前日期
        current_date_str = self.format_date(year, month, day)
        current_date_val = self.util.safe_int_convert(current_date_str, 19700101)
        
        # 从updated_at提取日期
        last_request_date_val = 19700101
        if updated_at_str:
            try:
                # 解析ISO格式时间：2023-12-26T14:37:11.123456
                dt = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
                # 转换为YYYYMMDD格式
                last_request_date_str = f"{dt.year:04d}{dt.month:02d}{dt.day:02d}"
                last_request_date_val = int(last_request_date_str)
            except (ValueError, AttributeError):
                last_request_date_val = 19700101
        
        # 初始化返回值
        allow_continue = True
        stop_message = " "
        new_usage_count = current_usage_val
        
        # 核心业务逻辑：用量限制判断
        if current_date_val > last_request_date_val:
            # 新的一天，重置计数器
            new_usage_count = 1
            allow_continue = True
            
        elif current_date_val == last_request_date_val:
            if new_usage_count < usage_limit:
                # 在同一天内，用量未达到限制
                new_usage_count += 1
                allow_continue = True
                
            elif new_usage_count == usage_limit:
                # 刚好达到限制，这是最后一次允许的请求
                new_usage_count += 1
                allow_continue = True
                
            else:
                # 已经超限，拒绝请求
                allow_continue = False
                stop_message = self.util.random_message(overusage_output) if overusage_output else "今日用量已达上限"
                
        else:
            # 日期异常（当前日期小于最后记录日期），保守策略：拒绝请求
            allow_continue = False
            stop_message = "日期异常，请稍后重试"
        
        # 如果允许继续，更新数据库
        if allow_continue or current_date_val > last_request_date_val:
            # 更新用量计数
            usage_result = self.mongo_system.update_field(
                bot_id, group_id, user_id, "daily_usage_count", new_usage_count
            )
            
            matched_count = usage_result.matched_count
            modified_count = usage_result.modified_count
        else:
            # 不允许继续，不更新数据库
            matched_count = 0
            modified_count = 0
        
        return {
            "allow_continue": allow_continue,
            "stop_message": stop_message,
            "new_usage_count": new_usage_count,
            "new_request_date": current_date_str,
            "usage_limit": usage_limit,
            "matched_count": matched_count,
            "modified_count": modified_count
        }


class FavorManager:
    """好感度管理器 - 核心业务逻辑"""
    
    def __init__(self, mongo_system: MongoDBSystem):
        self.mongo_system = mongo_system
        self.util = UtilityFunctions()
    
    def generate_favor_prompt(self, prompts: List[str], split_points: List[int], 
                             favor_value: int) -> str:
        """根据好感度值确定阶段提示词，使用分割点划分阶段。"""
        # 清洗并排序分割点（严格递增）
        valid_splits: List[int] = []
        prev_val: Optional[int] = None
        for split in split_points:
            try:
                split_int = int(split)
            except (TypeError, ValueError):
                continue
            if prev_val is None or split_int > prev_val:
                valid_splits.append(split_int)
                prev_val = split_int

        # 至少一个提示词
        if not prompts:
            prompts = ["好感度系统正常"]

        stage_count = len(valid_splits) + 1
        if len(prompts) > stage_count:
            prompts = prompts[:stage_count]
        elif len(prompts) < stage_count:
            prompts.extend([prompts[-1]] * (stage_count - len(prompts)))

        # 根据分割点定位阶段
        for idx, split_val in enumerate(valid_splits):
            if favor_value < split_val:
                return prompts[idx]
        return prompts[len(valid_splits)]
    
    def get_favor_prompt(self, bot_id: str, group_id: str, user_id: str,
                        prompts: List[str], split_points: List[int],
                        main_prompt: str) -> Dict[str, Any]:
        """
        获取好感度提示词并整合到主提示词中
        """
        # 获取当前用户好感度
        current_favor = self.mongo_system.get_field(bot_id, group_id, user_id, "favor_value")
        
        # 处理好感度值（确保是整数）
        try:
            favor_value = int(current_favor) if current_favor is not None else 0
        except (ValueError, TypeError):
            favor_value = 0
        
        # 生成好感度提示词
        favor_prompt = self.generate_favor_prompt(prompts, split_points, favor_value)
        
        # 构建完整提示词
        enhanced_prompt = f"{main_prompt}十分重要！{favor_prompt}。\n"
        
        return {
            "favor_value": favor_value,
            "favor_prompt": favor_prompt,
            "enhanced_main_prompt": enhanced_prompt
        }


class PersonaManager:
    """用户画像管理器 - 核心业务逻辑"""
    
    def __init__(self, mongo_system: MongoDBSystem):
        self.mongo_system = mongo_system
    
    def get_persona_prompt(self, bot_id: str, group_id: str, user_id: str,
                          main_prompt: str) -> Dict[str, Any]:
        """
        获取用户画像并整合到主提示词中
        """
        # 获取用户画像属性
        persona_attrs = self.mongo_system.get_field(bot_id, group_id, user_id, "persona_attributes")
        
        # 确保persona_attrs是字典类型
        if not isinstance(persona_attrs, dict):
            persona_attrs = {
                "basic_info": "",
                "living_habits": "",
                "psychological_traits": "",
                "interests_preferences": "",
                "dislikes": "",
                "ai_expectations": "",
                "memory_points": "",
            }
        
        # 提取各个画像字段
        basic_info = persona_attrs.get("basic_info", "")
        living_habits = persona_attrs.get("living_habits", "")
        psychological_traits = persona_attrs.get("psychological_traits", "")
        interests_preferences = persona_attrs.get("interests_preferences", "")
        dislikes = persona_attrs.get("dislikes", "")
        ai_expectations = persona_attrs.get("ai_expectations", "")
        memory_points = persona_attrs.get("memory_points", "")
        
        # 构建用户画像文本
        persona_parts = []
        if basic_info:
            persona_parts.append(f"基本信息: {basic_info}")
        if living_habits:
            persona_parts.append(f"生活习惯: {living_habits}")
        if psychological_traits:
            persona_parts.append(f"心理特征: {psychological_traits}")
        if interests_preferences:
            persona_parts.append(f"兴趣偏好: {interests_preferences}")
        if dislikes:
            persona_parts.append(f"反感点: {dislikes}")
        if ai_expectations:
            persona_parts.append(f"对AI的期望: {ai_expectations}")
        if memory_points:
            persona_parts.append(f"希望记住的信息: {memory_points}")
        
        # 如果没有任何画像信息，使用默认提示
        if not persona_parts:
            persona_text = "暂无用户画像信息"
        else:
            persona_text = "；".join(persona_parts)
        
        # 构建完整提示词（将用户画像加在主提示词后）
        enhanced_prompt = f"{main_prompt}\n用户画像：{persona_text}\n"
        
        return {
            "persona_text": persona_text,
            "persona_attributes": persona_attrs,
            "enhanced_main_prompt": enhanced_prompt
        }


class ContextManager:
    """上下文管理器 - 核心业务逻辑"""
    
    def __init__(self, mongo_system: MongoDBSystem):
        self.mongo_system = mongo_system
        self.util = UtilityFunctions()
    
    def get_context_prompt(self, bot_id: str, group_id: str, user_id: str,
                          context_pool_size: int, main_prompt: str) -> Dict[str, Any]:
        """
        获取上下文并整合到主提示词中
        从history_entries中取出最新的context_pool_size条消息
        格式：{时间:对方说XXX；你对此的反应是XXX}
        """
        # 获取历史对话记录
        history_entries = self.mongo_system.get_field(bot_id, group_id, user_id, "history_entries")
        
        # 确保history_entries是列表类型
        if not isinstance(history_entries, list):
            history_entries = []
        
        # 获取最新的context_pool_size条消息
        if context_pool_size <= 0:
            # 如果context_pool_size为0或负数，不提取任何上下文
            recent_histories = []
        else:
            # 从列表末尾取最新的几条
            recent_histories = history_entries[-context_pool_size:] if len(history_entries) > 0 else []
        
        # 构建上下文文本
        if not recent_histories:
            context_text = "暂无历史对话记录"
            enhanced_prompt = main_prompt
        else:
            # 将历史对话格式化为文本
            # 格式：{时间:对方说XXX；你对此的反应是XXX}
            context_parts = []
            for entry in recent_histories:
                if isinstance(entry, dict):
                    # 提取字段
                    created_at_raw = entry.get("created_at", "未知时间")
                    user_name = entry.get("user_name", "对方")
                    user_query = entry.get("user_query", "")
                    output = entry.get("output", {})
                    
                    # 格式化时间：从ISO格式转换为"年月日时分秒"
                    try:
                        # 解析ISO格式时间：2023-12-26T14:37:11.123456
                        dt = datetime.fromisoformat(created_at_raw.replace('Z', '+00:00'))
                        # 格式化为：2023年12月26日14时37分30秒
                        created_at = f"{dt.year}年{dt.month}月{dt.day}日{dt.hour}时{dt.minute}分{dt.second}秒"
                    except (ValueError, AttributeError):
                        created_at = "未知时间"
                    
                    # 处理output：如果是字典，提取response字段或转为字符串
                    if isinstance(output, dict):
                        bot_response = output.get("response", str(output))
                    else:
                        bot_response = str(output)
                    
                    # 格式化为单元：{时间:对方说XXX；你对此的反应是XXX}
                    context_unit = f"{{{created_at}:{user_name}说{user_query}；你对此的反应是{bot_response}}}"
                    context_parts.append(context_unit)
                elif isinstance(entry, str):
                    # 如果是字符串，直接添加
                    context_parts.append(entry)
                else:
                    # 其他类型，转换为字符串
                    context_parts.append(str(entry))
            
            context_text = "\n".join(context_parts)
            
            # 构建完整提示词（将上下文添加到主提示词中）
            enhanced_prompt = f"{main_prompt}\n历史对话上下文：\n{context_text}\n"
        
        return {
            "context_text": context_text,
            "context_count": len(recent_histories),
            "enhanced_main_prompt": enhanced_prompt
        }


class MemoryManager:
    """长期记忆管理器 - 核心业务逻辑"""
    
    def __init__(self, mongo_system: MongoDBSystem):
        self.mongo_system = mongo_system
        self.util = UtilityFunctions()
    
    def simple_tokenizer(self, text: str) -> List[str]:
        """简单分词器"""
        if not text:
            return []
        tokens = re.findall(r'[\w\u4e00-\u9fff]+', text.lower())
        return tokens
    
    def build_vocabulary(self, texts: List[str]) -> List[str]:
        """构建词汇表"""
        vocabulary = set()
        for text in texts:
            if text:
                vocabulary.update(self.simple_tokenizer(text))
        return sorted(vocabulary)
    
    def text_to_vector(self, text: str, vocabulary: List[str]) -> List[int]:
        """将文本转换为向量"""
        if not vocabulary or not text:
            return []
        token_counts = Counter(self.simple_tokenizer(text))
        return [token_counts.get(word, 0) for word in vocabulary]
    
    def cosine_similarity(self, vec1: List[int], vec2: List[int]) -> float:
        """计算余弦相似度"""
        if not vec1 or not vec2:
            return 0.0
            
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
            
        return dot_product / (norm1 * norm2)
    
    def get_memory_prompt(self, bot_id: str, group_id: str, user_id: str,
                         user_query: str, main_prompt: str,
                         memory_retrieval_number: int = 5) -> Dict[str, Any]:
        """
        获取长期记忆并整合到主提示词中
        从long_term_memory数组中检索相关记忆
        """
        # 获取长期记忆数组
        long_term_memory = self.mongo_system.get_field(bot_id, group_id, user_id, "long_term_memory")
        
        # 确保long_term_memory是列表类型
        if not isinstance(long_term_memory, list):
            long_term_memory = []
        
        # 如果没有记忆，直接返回
        if not long_term_memory or not user_query:
            return {
                "hit_memories": [],
                "enhanced_main_prompt": main_prompt
            }
        
        # 准备文本进行相似度计算
        # 假设每个记忆条目是字典格式：{"user_input": "...", "memory_description": "...", "hit_count": 0}
        memory_inputs = []
        for entry in long_term_memory:
            if isinstance(entry, dict):
                user_input = entry.get("user_input", "")
                if user_input:
                    memory_inputs.append(user_input)
            elif isinstance(entry, str):
                # 如果是字符串格式，直接使用
                memory_inputs.append(entry)
        
        if not memory_inputs:
            return {
                "hit_memories": [],
                "enhanced_main_prompt": main_prompt
            }
        
        # 构建词汇表和向量
        all_texts = memory_inputs + [user_query]
        vocabulary = self.build_vocabulary(all_texts)
        query_vector = self.text_to_vector(user_query, vocabulary)
        
        # 计算相似度并获取最相关的记忆
        similarities = []
        for i, user_input in enumerate(memory_inputs):
            if i >= len(long_term_memory):
                break
            memory_vector = self.text_to_vector(user_input, vocabulary)
            similarity = self.cosine_similarity(query_vector, memory_vector)
            similarities.append((similarity, i))
        
        # 获取top-k最相关的记忆
        similarities.sort(key=lambda x: x[0], reverse=True)
        top_k = min(memory_retrieval_number, len(similarities))
        top_indices = [item[1] for item in similarities[:top_k] if item[0] > 0]  # 只保留相似度>0的
        
        # 收集命中的记忆并更新命中次数
        hit_memories = []
        memory_descriptions = []
        
        for idx in top_indices:
            if idx < len(long_term_memory):
                entry = long_term_memory[idx]
                
                if isinstance(entry, dict):
                    # 字典格式
                    user_input = entry.get("user_input", "")
                    memory_desc = entry.get("memory_description", "")
                    hit_count = entry.get("hit_count", 0)
                    
                    # 更新命中次数
                    entry["hit_count"] = hit_count + 1
                    
                    hit_memories.append({
                        "user_input": user_input,
                        "memory_description": memory_desc,
                        "hit_count": hit_count + 1
                    })
                    
                    if memory_desc:
                        memory_descriptions.append(memory_desc)
                        
                elif isinstance(entry, str):
                    # 字符串格式，直接使用
                    hit_memories.append({"memory_description": entry, "hit_count": 1})
                    memory_descriptions.append(entry)
        
        # 更新数据库中的long_term_memory
        if hit_memories:
            self.mongo_system.update_field(bot_id, group_id, user_id, "long_term_memory", long_term_memory)
        
        # 构建增强的提示词
        if memory_descriptions:
            memory_text = "\n".join(memory_descriptions)
            enhanced_prompt = f"{main_prompt}\n\n相关记忆：\n{memory_text}\n"
        else:
            enhanced_prompt = main_prompt
        
        return {
            "hit_memories": hit_memories,
            "enhanced_main_prompt": enhanced_prompt
        }


class IntegratedWorkflow:
    """整合的工作流程序"""
    
    def __init__(self, mongo_url: str):
        self.mongo_system = MongoDBSystem(mongo_url)
        self.blacklist_manager = BlacklistManager(self.mongo_system)
        self.usage_limit_manager = UsageLimitManager(self.mongo_system)
        self.favor_manager = FavorManager(self.mongo_system)
        self.persona_manager = PersonaManager(self.mongo_system)
        self.context_manager = ContextManager(self.mongo_system)
        self.memory_manager = MemoryManager(self.mongo_system)
        self.util = UtilityFunctions()
    
    def step_1_blacklist_check(self, 
                               bot_id: str,
                               group_id: str,
                               user_id: str,
                               blacklist_system: str,
                               is_user_admin: str,
                               blacklist_restrict_admin_users: str,
                               warn_lifespan: str,
                               block_lifespan: str,
                               timestamp: float) -> Dict[str, Any]:
        """
        第1步：黑名单检查
        
        输入：
        - bot_id: 机器人ID
        - group_id: 群组ID
        - user_id: 用户ID
        - blacklist_system: 黑名单系统开关 ("enable"/"disable")
        - is_user_admin: 用户是否是管理员 ("true"/"false" 字符串)
        - blacklist_restrict_admin_users: 是否限制管理员 ("enable"/"disable")
        - warn_lifespan: 警告生命周期（秒）
        - block_lifespan: 封锁生命周期（秒）
        - timestamp: 当前时间戳
        
        返回：
        - continue_to_step_2: 是否继续到第2步
        - stop_reason: 停止原因（如果停止的话）
        - stop_message: 停止消息
        - block_status: 当前状态 (pass/warn/block)
        - matched_count: 匹配数量
        - modified_count: 修改数量
        """
        
        # 判断是否需要执行黑名单检查
        skip_blacklist_check = False
        
        # 条件1：黑名单系统被禁用
        if blacklist_system == "disable":
            skip_blacklist_check = True
        
        # 条件2：黑名单系统启用 且 不限制管理员 且 用户是管理员
        if (blacklist_system == "enable" and 
            blacklist_restrict_admin_users == "disable" and 
            is_user_admin == "true"):
            skip_blacklist_check = True
        
        # 如果跳过黑名单检查，直接进入第2步
        if skip_blacklist_check:
            return {
                "continue_to_step_2": True,
                "stop_reason": None,
                "stop_message": " ",
                "block_status": "pass",
                "matched_count": 0,
                "modified_count": 0
            }
        
        # 执行分支1.A：黑名单检查
        warn_lifespan_int = self.util.safe_int_convert(warn_lifespan, 0)
        block_lifespan_int = self.util.safe_int_convert(block_lifespan, 0)
        
        check_result = self.blacklist_manager.check_blacklist_status(
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            warn_lifespan=warn_lifespan_int,
            block_lifespan=block_lifespan_int,
            timestamp=timestamp
        )
        
        allow_continue = check_result["allow_continue"]
        block_status = check_result["block_status"]
        
        # 判断是否继续到第2步（基于allow_continue）
        if allow_continue:
            return {
                "continue_to_step_2": True,
                "stop_reason": None,
                "stop_message": check_result["stop_message"],
                "block_status": block_status,
                "matched_count": check_result["matched_count"],
                "modified_count": check_result["modified_count"]
            }
        else:
            # 停止程序
            return {
                "continue_to_step_2": False,
                "stop_reason": "block",
                "stop_message": check_result["stop_message"],
                "block_status": block_status,
                "matched_count": check_result["matched_count"],
                "modified_count": check_result["modified_count"]
            }
    
    def step_2_input_length_check(self,
                                  user_query: str,
                                  max_input_size: str,
                                  overinput_output: Any = None) -> Dict[str, Any]:
        """
        第2步：输入长度检查
        
        输入：
        - user_query: 用户查询字符串
        - max_input_size: 最大输入长度限制（字符串）
        
        返回：
        - continue_to_step_3: 是否继续到第3步
        - stop_reason: 停止原因（如果停止的话）
        - stop_message: 停止消息
        - input_length: 实际输入长度
        - max_length: 最大长度限制
        """
        
        
        
        # 转换max_input_size为整型
        max_length = self.util.safe_int_convert(max_input_size, 0)
        
        # 计算user_query的长度
        input_length = len(user_query) if user_query else 0
        
        # 判断是否满足长度要求
        # 条件：输入长度 < 长度限制 或者 长度限制为0（表示无限制）
        if input_length < max_length or max_length == 0:
            # 满足条件，继续到第3步
            return {
                "continue_to_step_3": True,
                "stop_reason": None,
                "stop_message": " ",
                "input_length": input_length,
                "max_length": max_length
            }
        else:
            # 不满足条件，终止程序
            stop_message = self.util.random_message(overinput_output) if overinput_output else "这么长谁看的过来啦……"
            return {
                "continue_to_step_3": False,
                "stop_reason": "input_exceeds_max_length",
                "stop_message": stop_message,
                "input_length": input_length,
                "max_length": max_length
            }
    
    def step_3_usage_limit_check(self,
                                 bot_id: str,
                                 group_id: str,
                                 user_id: str,
                                 usage_limit_system: str,
                                 usage_restrict_admin_users: str,
                                 is_user_admin: str,
                                 usage_limit: str,
                                 year: str,
                                 month: str,
                                 day: str,
                                 overusage_output: Any) -> Dict[str, Any]:
        """
        第3步：用量限制检查
        
        输入：
        - bot_id: 机器人ID
        - group_id: 群组ID
        - user_id: 用户ID
        - usage_limit_system: 用量限制系统开关 ("enable"/"disable")
        - usage_restrict_admin_users: 是否限制管理员 ("enable"/"disable")
        - is_user_admin: 用户是否是管理员 ("true"/"false" 字符串)
        - usage_limit: 每日用量限制（字符串）
        - year, month, day: 当前日期
        - overusage_output: 超限时的提示消息（字符串或字符串数组）
        
        返回：
        - continue_to_step_4: 是否继续到第4步
        - stop_reason: 停止原因（如果停止的话）
        - stop_message: 停止消息
        - usage_info: 用量信息
        - matched_count: 匹配数量
        - modified_count: 修改数量
        """
        
        # 判断是否需要执行用量限制检查
        skip_usage_check = False
        
        # 条件1：用量限制系统被禁用
        if usage_limit_system == "disable":
            skip_usage_check = True
        
        # 条件2：用量限制系统启用 且 不限制管理员 且 用户是管理员
        if (usage_limit_system == "enable" and 
            usage_restrict_admin_users == "disable" and 
            is_user_admin == "true"):
            skip_usage_check = True
        
        # 如果跳过用量限制检查，直接进入第4步
        if skip_usage_check:
            return {
                "continue_to_step_4": True,
                "stop_reason": None,
                "stop_message": " ",
                "usage_info": {
                    "current_usage": 0,
                    "usage_limit": 0,
                    "date": f"{year}{month}{day}"
                },
                "matched_count": 0,
                "modified_count": 0
            }
        
        # 执行分支3.A：用量限制检查
        usage_limit_int = self.util.safe_int_convert(usage_limit, 0)
        
        check_result = self.usage_limit_manager.check_usage_limit(
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            usage_limit=usage_limit_int,
            year=year,
            month=month,
            day=day,
            overusage_output=overusage_output
        )
        
        # 判断是否继续到第4步
        if check_result["allow_continue"]:
            return {
                "continue_to_step_4": True,
                "stop_reason": None,
                "stop_message": check_result["stop_message"],
                "usage_info": {
                    "current_usage": check_result["new_usage_count"],
                    "usage_limit": check_result["usage_limit"],
                    "date": check_result["new_request_date"]
                },
                "matched_count": check_result["matched_count"],
                "modified_count": check_result["modified_count"]
            }
        else:
            # 停止程序
            return {
                "continue_to_step_4": False,
                "stop_reason": "overusage",
                "stop_message": check_result["stop_message"],
                "usage_info": {
                    "current_usage": check_result["new_usage_count"],
                    "usage_limit": check_result["usage_limit"],
                    "date": check_result["new_request_date"]
                },
                "matched_count": check_result["matched_count"],
                "modified_count": check_result["modified_count"]
            }
    
    def step_4_favor_prompt(self,
                           bot_id: str,
                           group_id: str,
                           user_id: str,
                           favor_system: str,
                           favor_prompts: Optional[List[str]],
                           favor_split_points: Optional[List[int]],
                           main_prompt: str) -> Dict[str, Any]:
        """
        第4步：好感度提示词生成
        
        输入：
        - bot_id: 机器人ID
        - group_id: 群组ID
        - user_id: 用户ID
        - favor_system: 好感度系统开关 ("enable"/"disable")
        - favor_prompts: 好感度提示词数组
        - favor_split_points: 分割点整型数组
        - main_prompt: 主提示词
        
        返回：
        - continue_to_step_5: 是否继续到第5步
        - favor_value: 用户好感度值
        - favor_prompt: 好感度提示词
        - enhanced_main_prompt: 增强后的主提示词
        """
        
        # 判断是否需要执行好感度系统
        if favor_system == "disable":
            # 好感度系统被禁用，直接进入第5步
            return {
                "continue_to_step_5": True,
                "favor_value": 0,
                "favor_prompt": "",
                "enhanced_main_prompt": main_prompt
            }
        
        # 执行分支4.A：好感度提示词生成
        prompts = favor_prompts or []
        split_points = favor_split_points or []
        
        result = self.favor_manager.get_favor_prompt(
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            prompts=prompts,
            split_points=split_points,
            main_prompt=main_prompt
        )
        
        return {
            "continue_to_step_5": True,
            "favor_value": result["favor_value"],
            "favor_prompt": result["favor_prompt"],
            "enhanced_main_prompt": result["enhanced_main_prompt"]
        }
    
    def step_5_persona_prompt(self,
                             bot_id: str,
                             group_id: str,
                             user_id: str,
                             persona_system: str,
                             main_prompt: str) -> Dict[str, Any]:
        """
        第5步：用户画像提示词生成
        
        输入：
        - bot_id: 机器人ID
        - group_id: 群组ID
        - user_id: 用户ID
        - persona_system: 用户画像系统开关 ("enable"/"disable")
        - main_prompt: 主提示词（可能已经包含好感度提示词）
        
        返回：
        - continue_to_step_6: 是否继续到第6步
        - persona_text: 用户画像文本
        - enhanced_main_prompt: 增强后的主提示词
        """
        
        # 判断是否需要执行用户画像系统
        if persona_system == "disable":
            # 用户画像系统被禁用，直接进入第6步
            return {
                "continue_to_step_6": True,
                "persona_text": "",
                "enhanced_main_prompt": main_prompt
            }
        
        # 执行分支5.A：用户画像提示词生成
        result = self.persona_manager.get_persona_prompt(
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            main_prompt=main_prompt
        )
        
        return {
            "continue_to_step_6": True,
            "persona_text": result["persona_text"],
            "enhanced_main_prompt": result["enhanced_main_prompt"]
        }
    
    def step_6_context_prompt(self,
                             bot_id: str,
                             group_id: str,
                             user_id: str,
                             context_system: str,
                             context_pool_size: str,
                             main_prompt: str) -> Dict[str, Any]:
        """
        第6步：上下文提示词生成
        
        输入：
        - bot_id: 机器人ID
        - group_id: 群组ID
        - user_id: 用户ID
        - context_system: 上下文系统开关 ("enable"/"disable")
        - context_pool_size: 上下文池大小（字符串形式的数字）
        - main_prompt: 主提示词（可能已经包含好感度和用户画像提示词）
        
        返回：
        - continue_to_step_7: 是否继续到第7步
        - context_text: 上下文文本
        - enhanced_main_prompt: 增强后的主提示词
        """
        
        # 判断是否需要执行上下文系统
        if context_system == "disable":
            # 上下文系统被禁用，直接进入第7步
            return {
                "continue_to_step_7": True,
                "context_text": "",
                "enhanced_main_prompt": main_prompt
            }
        
        # 执行分支6.A：上下文提示词生成
        # 转换context_pool_size为整型
        pool_size = self.util.safe_int_convert(context_pool_size, 0)
        
        result = self.context_manager.get_context_prompt(
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            context_pool_size=pool_size,
            main_prompt=main_prompt
        )
        
        return {
            "continue_to_step_7": True,
            "context_text": result["context_text"],
            "context_count": result["context_count"],
            "enhanced_main_prompt": result["enhanced_main_prompt"]
        }
    
    def step_7_memory_prompt(self,
                            bot_id: str,
                            group_id: str,
                            user_id: str,
                            memory_system: str,
                            user_query: str,
                            memory_retrieval_number: str,
                            main_prompt: str) -> Dict[str, Any]:
        """
        第7步：长期记忆提示词生成（最后一步）
        
        输入：
        - bot_id: 机器人ID
        - group_id: 群组ID
        - user_id: 用户ID
        - memory_system: 长期记忆系统开关 ("enable"/"disable")
        - user_query: 用户查询内容
        - memory_retrieval_number: 记忆检索数量（字符串形式的数字）
        - main_prompt: 主提示词（可能已经包含好感度、用户画像、上下文提示词）
        
        返回：
        - stop_reason: "finish" - 表示工作流完成
        - stop_message: " " - 空格字符串
        - hit_memories: 命中的记忆条目列表
        - enhanced_main_prompt: 最终的增强主提示词
        """
        
        # 判断是否需要执行长期记忆系统
        if memory_system == "disable":
            # 长期记忆系统被禁用，程序结束
            return {
                "stop_reason": "finish",
                "stop_message": " ",
                "hit_memories": [],
                "enhanced_main_prompt": main_prompt
            }
        
        # 执行分支7.A：长期记忆检索
        # 转换memory_retrieval_number为整型
        retrieval_num = self.util.safe_int_convert(memory_retrieval_number, 5)
        
        result = self.memory_manager.get_memory_prompt(
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            user_query=user_query,
            main_prompt=main_prompt,
            memory_retrieval_number=retrieval_num
        )
        
        return {
            "stop_reason": "finish",
            "stop_message": " ",
            "hit_memories": result["hit_memories"],
            "enhanced_main_prompt": result["enhanced_main_prompt"]
        }


def main(
    # 基础参数
    bot_id: str,
    group_id: str,
    user_id: str,
    user_query: str,
    main_prompt: str,
    MONGO_URL: str,

    # 跨群配置参数（用于9999模板继承逻辑）
    favor_cross_group: str = "disable",
    persona_cross_group: str = "disable",
    blacklist_cross_group: str = "disable",
    usage_limit_cross_group: str = "disable",

    # 第1步：黑名单检查参数
    blacklist_system: str = "disable",
    is_user_admin: str = "false",
    blacklist_restrict_admin_users: str = "disable",
    warn_lifespan: str = "0",
    block_lifespan: str = "0",
    timestamp: float = 0.0,

    # 第2步：输入长度检查参数
    max_input_size: str = "0",
    overinput_output: Any = None,

    # 第3步：用量限制检查参数
    usage_limit_system: str = "disable",
    usage_restrict_admin_users: str = "disable",
    usage_limit: str = "0",
    year: str = "1970",
    month: str = "01",
    day: str = "01",
    overusage_output: Any = None,

    # 第4步：好感度提示词参数
    favor_system: str = "disable",
    favor_prompts: Optional[List[str]] = None,
    favor_split_points: Optional[List[int]] = None,

    # 第5步：用户画像提示词参数
    persona_system: str = "disable",

    # 第6步：上下文提示词参数
    context_system: str = "disable",
    context_pool_size: str = "0",

    # 第7步：长期记忆提示词参数
    memory_system: str = "disable",
    memory_retrieval_number: str = "5"
) -> Dict[str, Any]:
    """
    整合工作流主函数 - 完整的7步工作流

    执行顺序：
    1. 黑名单检查 -> 可能终止
    2. 输入长度检查 -> 可能终止
    3. 用量限制检查 -> 可能终止
    4. 好感度提示词生成
    5. 用户画像提示词生成
    6. 上下文提示词生成
    7. 长期记忆提示词生成 -> 返回最终结果

    跨群配置说明：
    - favor_cross_group: 好感度是否跨群共享
    - persona_cross_group: 用户画像是否跨群共享
    - blacklist_cross_group: 黑名单状态是否跨群共享
    - usage_limit_cross_group: 用量统计是否跨群共享

    返回：包含各步骤结果和最终增强的主提示词的字典
    """

    # 初始化工作流
    workflow = IntegratedWorkflow(MONGO_URL)

    # 设置跨群配置到MongoDBSystem实例
    workflow.mongo_system.set_cross_group_config(
        favor_cross_group=favor_cross_group,
        persona_cross_group=persona_cross_group,
        blacklist_cross_group=blacklist_cross_group,
        usage_limit_cross_group=usage_limit_cross_group
    )
    # 第1步：黑名单检查
    step1_result = workflow.step_1_blacklist_check(
        bot_id=bot_id,
        group_id=group_id,
        user_id=user_id,
        blacklist_system=blacklist_system,
        is_user_admin=is_user_admin,
        blacklist_restrict_admin_users=blacklist_restrict_admin_users,
        warn_lifespan=warn_lifespan,
        block_lifespan=block_lifespan,
        timestamp=timestamp
    )
    
    # 如果黑名单检查未通过，立即返回（展平的字典，包含所有字段的默认值）
    if not step1_result.get("continue_to_step_2", False):
        return {
            "stop_reason": step1_result["stop_reason"],
            "stop_message": step1_result["stop_message"],
            "step_stopped_at": 1,
            "main_prompt": main_prompt,
            # 步骤1结果
            "block_status": step1_result.get("block_status", "pass"),
            "block_message": step1_result.get("stop_message", " "),
            # 步骤2结果（默认值）
            "step2_input_length": 0,
            "step2_max_length": 0,
            # 步骤3结果（默认值）
            "step3_current_usage": 0,
            "step3_usage_limit": 0,
            "step3_usage_date": " ",
            # 步骤4结果（默认值）
            "favor_value": 0,
            "favor_prompt": " ",
            # 步骤5结果（默认值）
            "persona": " ",
            # 步骤6结果（默认值）
            "context": " ",
            "step6_context_count": 0,
            # 步骤7结果（默认值）
            "step7_hit_memories": " "
        }
    
    # 第2步：输入长度检查
    step2_result = workflow.step_2_input_length_check(
        user_query=user_query,
        max_input_size=max_input_size,
        overinput_output=overinput_output
    )
    
    # 如果输入长度检查未通过，立即返回（展平的字典，包含所有字段的默认值）
    if not step2_result.get("continue_to_step_3", False):
        return {
            "stop_reason": step2_result["stop_reason"],
            "stop_message": step2_result["stop_message"],
            "step_stopped_at": 2,
            "main_prompt": main_prompt,
            # 步骤1结果
            "block_status": step1_result.get("block_status", "pass"),
            "block_message": step1_result.get("stop_message", " "),
            # 步骤2结果
            "step2_input_length": step2_result.get("input_length", 0),
            "step2_max_length": step2_result.get("max_length", 0),
            # 步骤3结果（默认值）
            "step3_current_usage": 0,
            "step3_usage_limit": 0,
            "step3_usage_date": " ",
            # 步骤4结果（默认值）
            "favor_value": 0,
            "favor_prompt": " ",
            # 步骤5结果（默认值）
            "persona": " ",
            # 步骤6结果（默认值）
            "context": " ",
            "step6_context_count": 0,
            # 步骤7结果（默认值）
            "step7_hit_memories": " "
        }
    
    # 第3步：用量限制检查
    step3_result = workflow.step_3_usage_limit_check(
        bot_id=bot_id,
        group_id=group_id,
        user_id=user_id,
        usage_limit_system=usage_limit_system,
        usage_restrict_admin_users=usage_restrict_admin_users,
        is_user_admin=is_user_admin,
        usage_limit=usage_limit,
        year=year,
        month=month,
        day=day,
        overusage_output=overusage_output
    )
    
    # 如果用量限制检查未通过，立即返回（展平的字典，包含所有字段的默认值）
    if not step3_result.get("continue_to_step_4", False):
        usage_info = step3_result.get("usage_info", {})
        return {
            "stop_reason": step3_result["stop_reason"],
            "stop_message": step3_result["stop_message"],
            "step_stopped_at": 3,
            "main_prompt": main_prompt,
            # 步骤1结果
            "block_status": step1_result.get("block_status", "pass"),
            "block_message": step1_result.get("stop_message", " "),
            # 步骤2结果
            "step2_input_length": step2_result.get("input_length", 0),
            "step2_max_length": step2_result.get("max_length", 0),
            # 步骤3结果
            "step3_current_usage": usage_info.get("current_usage", 0),
            "step3_usage_limit": usage_info.get("usage_limit", 0),
            "step3_usage_date": usage_info.get("date", " "),
            # 步骤4结果（默认值）
            "favor_value": 0,
            "favor_prompt": " ",
            # 步骤5结果（默认值）
            "persona": " ",
            # 步骤6结果（默认值）
            "context": " ",
            "step6_context_count": 0,
            # 步骤7结果（默认值）
            "step7_hit_memories": " "
        }
    
    # 第4步：好感度提示词生成
    step4_result = workflow.step_4_favor_prompt(
        bot_id=bot_id,
        group_id=group_id,
        user_id=user_id,
        favor_system=favor_system,
        favor_prompts=favor_prompts,
        favor_split_points=favor_split_points,
        main_prompt=main_prompt
    )
    
    # 更新主提示词
    current_prompt = step4_result["enhanced_main_prompt"]
    
    # 第5步：用户画像提示词生成
    step5_result = workflow.step_5_persona_prompt(
        bot_id=bot_id,
        group_id=group_id,
        user_id=user_id,
        persona_system=persona_system,
        main_prompt=current_prompt
    )
    
    # 更新主提示词
    current_prompt = step5_result["enhanced_main_prompt"]
    
    # 第6步：上下文提示词生成
    step6_result = workflow.step_6_context_prompt(
        bot_id=bot_id,
        group_id=group_id,
        user_id=user_id,
        context_system=context_system,
        context_pool_size=context_pool_size,
        main_prompt=current_prompt
    )
    
    # 更新主提示词
    current_prompt = step6_result["enhanced_main_prompt"]
    
    # 第7步：长期记忆提示词生成（最后一步）
    step7_result = workflow.step_7_memory_prompt(
        bot_id=bot_id,
        group_id=group_id,
        user_id=user_id,
        memory_system=memory_system,
        user_query=user_query,
        memory_retrieval_number=memory_retrieval_number,
        main_prompt=current_prompt
    )
    
    # 获取usage_info以展平字典
    usage_info = step3_result.get("usage_info", {})
    
    # 构建展平的返回结果字典（不包含嵌套字典）
    return {
        "stop_reason": "finish",
        "stop_message": " ",
        "step_stopped_at": 7,
        "main_prompt": step7_result["enhanced_main_prompt"],
        # 步骤1结果（展平）
        "block_status": step1_result.get("block_status", "pass"),
        "block_message": step1_result.get("stop_message", " "),
        # 步骤2结果（展平）
        "step2_input_length": step2_result.get("input_length", 0),
        "step2_max_length": step2_result.get("max_length", 0),
        # 步骤3结果（展平）
        "step3_current_usage": usage_info.get("current_usage", 0),
        "step3_usage_limit": usage_info.get("usage_limit", 0),
        "step3_usage_date": usage_info.get("date", ""),
        # 步骤4结果（展平）
        "favor_value": step4_result.get("favor_value", 0),
        "favor_prompt": step4_result.get("favor_prompt", ""),
        # 步骤5结果（展平）
        "persona": step5_result.get("persona_text", ""),
        # 步骤6结果（展平）
        "context": step6_result.get("context_text", ""),
        "step6_context_count": step6_result.get("context_count", 0),
        # 步骤7结果（展平，将hit_memories转为JSON字符串）
        "step7_hit_memories": json.dumps(step7_result.get("hit_memories", []), ensure_ascii=False)
    }
