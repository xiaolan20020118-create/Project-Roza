import pymongo
from datetime import datetime
import re
import json
import math
import random
from collections import Counter
from typing import Dict, Any, Optional, Tuple, List, Union


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
        ], unique=True, name="idx_user_data")

        # 跨群配置（默认值，使用布尔类型）
        self._favor_cross_group: bool = False
        self._persona_cross_group: bool = False
        self._blacklist_cross_group: bool = False
        self._usage_limit_cross_group: bool = False

    def set_cross_group_config(self, favor_cross_group: Any = False,
                               persona_cross_group: Any = False,
                               blacklist_cross_group: Any = False,
                               usage_limit_cross_group: Any = False):
        """
        设置跨群配置参数

        参数：
            favor_cross_group: 好感度是否跨群（支持bool/int，自动转换为bool）
            persona_cross_group: 用户画像是否跨群
            blacklist_cross_group: 黑名单是否跨群
            usage_limit_cross_group: 用量统计是否跨群
        """
        self._favor_cross_group = bool(favor_cross_group)
        self._persona_cross_group = bool(persona_cross_group)
        self._blacklist_cross_group = bool(blacklist_cross_group)
        self._usage_limit_cross_group = bool(usage_limit_cross_group)

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
        def get_value(field_name: str, default_value: Any, cross_group_enabled: bool) -> Any:
            if template_doc and cross_group_enabled:
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

    def _init_context(self, bot_id: str, group_id: str, user_id: str,
                      user_query: str, main_prompt: str) -> Dict[str, Any]:
        """初始化工作流上下文，设置所有字段的默认值"""
        return {
            # 工作流状态
            "stop_reason": None,
            "stop_message": " ",
            # 用户标识
            "bot_id": bot_id,
            "group_id": group_id,
            "user_id": user_id,
            # 输入
            "user_query": user_query,
            # 输出
            "main_prompt": main_prompt,
            # 步骤1：黑名单检查结果
            "block_status": "pass",
            # 步骤2：输入长度检查结果
            "input_length": 0,
            "max_input_length": 0,
            # 步骤3：用量限制检查结果
            "current_usage": 0,
            "usage_limit": 0,
            "usage_date": "",
            # 步骤4：好感度结果
            "favor_value": 0,
            "favor_prompt": "",
            # 步骤5：用户画像结果
            "persona_text": "",
            # 步骤6：上下文结果
            "context_text": "",
            "context_count": 0,
            # 步骤7：记忆结果
            "hit_memories": [],
        }

    def check_blacklist(self, context: Dict[str, Any],
                       blacklist_system: Any, is_user_admin: Any,
                       blacklist_restrict_admin_users: Any,
                       warn_lifespan: str, block_lifespan: str,
                       timestamp: float) -> Dict[str, Any]:
        """黑名单检查"""
        # 判断是否需要执行黑名单检查
        skip_check = (
            not blacklist_system or
            (blacklist_system and
             not blacklist_restrict_admin_users and
             is_user_admin)
        )

        if skip_check:
            return context

        # 执行黑名单检查
        warn_lifespan_int = self.util.safe_int_convert(warn_lifespan, 0)
        block_lifespan_int = self.util.safe_int_convert(block_lifespan, 0)

        check_result = self.blacklist_manager.check_blacklist_status(
            bot_id=context["bot_id"],
            group_id=context["group_id"],
            user_id=context["user_id"],
            warn_lifespan=warn_lifespan_int,
            block_lifespan=block_lifespan_int,
            timestamp=timestamp
        )

        # 更新 context
        context["block_status"] = "pass" if check_result["block_status"] else "block"

        if not check_result["allow_continue"]:
            context["stop_reason"] = "block"
            context["stop_message"] = check_result["stop_message"]

        return context

    def check_input_length(self, context: Dict[str, Any],
                          max_input_size: str,
                          overinput_output: Any = None) -> Dict[str, Any]:
        """输入长度检查"""
        max_length = self.util.safe_int_convert(max_input_size, 0)
        input_length = len(context["user_query"]) if context["user_query"] else 0

        context["input_length"] = input_length
        context["max_input_length"] = max_length

        # 判断是否满足长度要求
        if input_length >= max_length and max_length > 0:
            context["stop_reason"] = "input_exceeds_max_length"
            context["stop_message"] = self.util.random_message(overinput_output) if overinput_output else "这么长谁看的过来啦……"

        return context

    def check_usage_limit(self, context: Dict[str, Any],
                         usage_limit_system: Any, usage_restrict_admin_users: Any,
                         is_user_admin: Any, usage_limit: str,
                         year: str, month: str, day: str,
                         overusage_output: Any) -> Dict[str, Any]:
        """用量限制检查"""
        # 判断是否需要执行用量限制检查
        skip_check = (
            not usage_limit_system or
            (usage_limit_system and
             not usage_restrict_admin_users and
             is_user_admin)
        )

        if skip_check:
            return context

        usage_limit_int = self.util.safe_int_convert(usage_limit, 0)

        check_result = self.usage_limit_manager.check_usage_limit(
            bot_id=context["bot_id"],
            group_id=context["group_id"],
            user_id=context["user_id"],
            usage_limit=usage_limit_int,
            year=year,
            month=month,
            day=day,
            overusage_output=overusage_output
        )

        # 更新 context
        context["current_usage"] = check_result["new_usage_count"]
        context["usage_limit"] = check_result["usage_limit"]
        context["usage_date"] = check_result["new_request_date"]

        if not check_result["allow_continue"]:
            context["stop_reason"] = "overusage"
            context["stop_message"] = check_result["stop_message"]

        return context

    def generate_favor_prompt(self, context: Dict[str, Any],
                             favor_system: Any,
                             favor_prompts: Optional[List[str]],
                             favor_split_points: Optional[List[int]]) -> Dict[str, Any]:
        """好感度提示词生成"""
        if not favor_system:
            return context

        prompts = favor_prompts or []
        split_points = favor_split_points or []

        result = self.favor_manager.get_favor_prompt(
            bot_id=context["bot_id"],
            group_id=context["group_id"],
            user_id=context["user_id"],
            prompts=prompts,
            split_points=split_points,
            main_prompt=context["main_prompt"]
        )

        context["favor_value"] = result["favor_value"]
        context["favor_prompt"] = result["favor_prompt"]
        context["main_prompt"] = result["enhanced_main_prompt"]

        return context

    def generate_persona_prompt(self, context: Dict[str, Any],
                              persona_system: Any) -> Dict[str, Any]:
        """用户画像提示词生成"""
        if not persona_system:
            return context

        result = self.persona_manager.get_persona_prompt(
            bot_id=context["bot_id"],
            group_id=context["group_id"],
            user_id=context["user_id"],
            main_prompt=context["main_prompt"]
        )

        context["persona_text"] = result["persona_text"]
        context["main_prompt"] = result["enhanced_main_prompt"]

        return context

    def generate_context_prompt(self, context: Dict[str, Any],
                               context_system: Any,
                               context_pool_size: str) -> Dict[str, Any]:
        """上下文提示词生成"""
        if not context_system:
            return context

        pool_size = self.util.safe_int_convert(context_pool_size, 0)

        result = self.context_manager.get_context_prompt(
            bot_id=context["bot_id"],
            group_id=context["group_id"],
            user_id=context["user_id"],
            context_pool_size=pool_size,
            main_prompt=context["main_prompt"]
        )

        context["context_text"] = result["context_text"]
        context["context_count"] = result["context_count"]
        context["main_prompt"] = result["enhanced_main_prompt"]

        return context

    def generate_memory_prompt(self, context: Dict[str, Any],
                             memory_system: Any,
                             memory_retrieval_number: str) -> Dict[str, Any]:
        """长期记忆提示词生成"""
        if not memory_system:
            return context

        retrieval_num = self.util.safe_int_convert(memory_retrieval_number, 5)

        result = self.memory_manager.get_memory_prompt(
            bot_id=context["bot_id"],
            group_id=context["group_id"],
            user_id=context["user_id"],
            user_query=context["user_query"],
            main_prompt=context["main_prompt"],
            memory_retrieval_number=retrieval_num
        )

        context["hit_memories"] = result["hit_memories"]
        context["main_prompt"] = result["enhanced_main_prompt"]

        return context


def main(
    # 基础参数
    bot_id: str,
    group_id: str,
    user_id: str,
    user_query: str,
    main_prompt: str,
    MONGO_URL: str,

    # 跨群配置参数（支持bool/str/int，自动转换为bool内部处理）
    favor_cross_group: Any = False,
    persona_cross_group: Any = False,
    blacklist_cross_group: Any = False,
    usage_limit_cross_group: Any = False,

    # 黑名单检查参数
    blacklist_system: Any = 0,
    is_user_admin: Any = 0,
    blacklist_restrict_admin_users: Any = 0,
    warn_lifespan: str = "0",
    block_lifespan: str = "0",
    timestamp: float = 0.0,

    # 输入长度检查参数
    max_input_size: str = "0",
    overinput_output: Any = None,

    # 用量限制检查参数
    usage_limit_system: Any = 0,
    usage_restrict_admin_users: Any = 0,
    usage_limit: str = "0",
    year: str = "1970",
    month: str = "01",
    day: str = "01",
    overusage_output: Any = None,

    # 好感度提示词参数
    favor_system: Any = 0,
    favor_prompts: Optional[List[str]] = None,
    favor_split_points: Optional[List[int]] = None,

    # 用户画像提示词参数
    persona_system: Any = 0,

    # 上下文提示词参数
    context_system: Any = 0,
    context_pool_size: str = "0",

    # 长期记忆提示词参数
    memory_system: Any = 0,
    memory_retrieval_number: str = "5"
) -> Dict[str, Any]:
    """
    整合工作流主函数

    执行顺序：
    1. 黑名单检查 -> 可能终止
    2. 输入长度检查 -> 可能终止
    3. 用量限制检查 -> 可能终止
    4. 好感度提示词生成
    5. 用户画像提示词生成
    6. 上下文提示词生成
    7. 长期记忆提示词生成 -> 返回最终结果

    返回：包含完整字段的字典（无论在哪一步结束）
    """

    # 初始化工作流
    workflow = IntegratedWorkflow(MONGO_URL)

    # 设置跨群配置
    workflow.mongo_system.set_cross_group_config(favor_cross_group, persona_cross_group, blacklist_cross_group, usage_limit_cross_group)

    # 初始化上下文
    context = workflow._init_context(bot_id, group_id, user_id, user_query, main_prompt)

    # 步骤1：黑名单检查
    context = workflow.check_blacklist(
        context,
        blacklist_system, is_user_admin, blacklist_restrict_admin_users,
        warn_lifespan, block_lifespan, timestamp
    )
    if context["stop_reason"] is not None:
        return context

    # 步骤2：输入长度检查
    context = workflow.check_input_length(context, max_input_size, overinput_output)
    if context["stop_reason"] is not None:
        return context

    # 步骤3：用量限制检查
    context = workflow.check_usage_limit(
        context,
        usage_limit_system, usage_restrict_admin_users, is_user_admin,
        usage_limit, year, month, day, overusage_output
    )
    if context["stop_reason"] is not None:
        return context

    # 步骤4：好感度提示词生成
    context = workflow.generate_favor_prompt(context, favor_system, favor_prompts, favor_split_points)

    # 步骤5：用户画像提示词生成
    context = workflow.generate_persona_prompt(context, persona_system)

    # 步骤6：上下文提示词生成
    context = workflow.generate_context_prompt(context, context_system, context_pool_size)

    # 步骤7：长期记忆提示词生成
    context = workflow.generate_memory_prompt(context, memory_system, memory_retrieval_number)

    # 标记工作流成功完成
    context["stop_reason"] = "finish"

    # 返回完整结果
    return context
