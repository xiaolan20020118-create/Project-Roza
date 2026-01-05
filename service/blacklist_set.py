import pymongo
from datetime import datetime
from typing import Dict, Any


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


class BlacklistUpdater:
    """黑名单状态更新器 - 核心业务逻辑（新版本）"""
    
    def __init__(self, mongo_system: MongoDBSystem):
        self.mongo_system = mongo_system
    
    def calculate_new_status(self, bot_id: str, group_id: str, user_id: str,
                            block_status: bool, warn_count_threshold: int,
                            warn_lifespan: int, timestamp: float) -> Dict[str, Any]:
        """
        计算新的屏蔽状态
        新逻辑：只在block_status=True时更新
        
        参数：
        - bot_id, group_id, user_id: 用户标识
        - block_status: 当前状态 (True=pass, False=block)
        - warn_count_threshold: 警告次数阈值
        - warn_lifespan: 警告生命周期（秒）
        - timestamp: 当前时间戳
        
        返回：
        - new_block_status: 新的block_status值
        - new_block_count: 新的block_count值
        - need_update: 是否需要更新数据库
        - block_message: 封禁消息
        """
        
        # 只在block_status=True时处理
        if block_status is not True:
            return {
                "new_block_status": block_status,
                "new_block_count": 0,
                "need_update": False,
                "block_message": " "
            }
        
        # 获取当前的block_stats
        document = self.mongo_system.collection.find_one({
            "bot_id": bot_id,
            "group_id": group_id,
            "user_id": user_id
        })
        
        if not document or "block_stats" not in document:
            block_stats = {
                "block_status": True,
                "block_count": 0,
                "last_operate_time": datetime.utcnow().isoformat()
            }
        else:
            block_stats = document["block_stats"]
        
        current_block_count = block_stats.get("block_count", 0)
        last_operate_time_str = block_stats.get("last_operate_time", datetime.utcnow().isoformat())
        
        # 解析last_operate_time
        try:
            last_operate_dt = datetime.fromisoformat(last_operate_time_str.replace('Z', '+00:00'))
            last_operate_timestamp = last_operate_dt.timestamp()
        except (ValueError, AttributeError):
            last_operate_timestamp = timestamp
        
        # 计算时间差
        delta_time = timestamp - last_operate_timestamp
        
        # 核心业务逻辑
        if delta_time >= warn_lifespan:
            # 时间差大于warn_lifespan，重置block_count为1
            new_block_count = 1
            new_block_status = True
            block_message = "[warn]"
        else:
            # 时间差不大于warn_lifespan，block_count加1
            new_block_count = current_block_count + 1
            
            # 判断是否达到阈值
            if new_block_count < warn_count_threshold:
                # 小于阈值，保持pass状态
                new_block_status = True
                block_message = "[warn]"
            else:
                # 达到或超过阈值，设置为block状态
                new_block_status = False
                block_message = "\n无语了，你自己冷静冷静吧"
        
        return {
            "new_block_status": new_block_status,
            "new_block_count": new_block_count,
            "need_update": True,
            "block_message": block_message
        }
    
    def update_blacklist_single_group(self, bot_id: str, group_id: str, user_id: str,
                                      new_block_status: bool, new_block_count: int) -> Dict[str, Any]:
        """
        更新单个群组的黑名单状态
        
        返回：
        - matched_count: 匹配的文档数
        - modified_count: 修改的文档数
        """
        current_time = datetime.utcnow().isoformat()
        
        # 构建block_stats更新
        block_stats_update = {
            "block_status": new_block_status,
            "block_count": new_block_count,
            "last_operate_time": current_time
        }
        
        result = self.mongo_system.collection.update_one(
            {
                "bot_id": bot_id,
                "group_id": group_id,
                "user_id": user_id
            },
            {
                "$set": {
                    "block_stats": block_stats_update,
                    "updated_at": current_time
                }
            },
            upsert=True
        )
        
        return {
            "matched_count": result.matched_count,
            "modified_count": result.modified_count
        }
    
    def update_blacklist_cross_group(self, bot_id: str, user_id: str,
                                     new_block_status: bool, new_block_count: int) -> Dict[str, Any]:
        """
        跨群组更新黑名单状态
        更新所有bot_id相同且user_id相同的文档
        
        返回：
        - matched_count: 匹配的文档数
        - modified_count: 修改的文档数
        """
        current_time = datetime.utcnow().isoformat()
        
        # 构建block_stats更新
        block_stats_update = {
            "block_status": new_block_status,
            "block_count": new_block_count,
            "last_operate_time": current_time
        }
        
        result = self.mongo_system.collection.update_many(
            {
                "bot_id": bot_id,
                "user_id": user_id
            },
            {
                "$set": {
                    "block_stats": block_stats_update,
                    "updated_at": current_time
                }
            }
        )
        
        return {
            "matched_count": result.matched_count,
            "modified_count": result.modified_count
        }


def main(
    blacklist_system: str,
    warn_lifespan: str,
    warn_count: str,
    timestamp: float,
    bot_id: str,
    group_id: str,
    user_id: str,
    MONGO_URL: str,
    blacklist_cross_group: str,
    block_status: bool
) -> Dict[str, Any]:
    """
    黑名单状态更新主函数（新版本）
    
    参数：
    - blacklist_system: 黑名单系统开关 ("enable"/"disable")
    - warn_lifespan: 警告生命周期（秒，字符串）
    - warn_count: 警告次数阈值（字符串）
    - timestamp: 当前时间戳（浮点数）
    - bot_id: 机器人ID
    - group_id: 群组ID
    - user_id: 用户ID
    - MONGO_URL: MongoDB连接URL
    - blacklist_cross_group: 是否跨群组更新 ("enable"/"disable")
    - block_status: 当前状态（布尔：True=pass, False=block）
    
    返回：
    - new_block_status: 更新后的状态（布尔）
    - block_count: 当前违规计数
    - block_message: 封禁消息
    - matched_count: 匹配的文档数量
    - modified_count: 修改的文档数量
    """
    
    # 如果黑名单系统被禁用，直接返回默认值
    if blacklist_system == "disable":
        return {
            "new_block_status": True,
            "block_count": 0,
            "block_message": " ",
            "matched_count": 0,
            "modified_count": 0
        }
    
    # 初始化系统
    mongo_system = MongoDBSystem(MONGO_URL)
    blacklist_updater = BlacklistUpdater(mongo_system)
    
    # 转换warn_count和warn_lifespan为整数
    try:
        warn_count_int = int(warn_count) if warn_count else 3
    except (ValueError, TypeError):
        warn_count_int = 3
    
    try:
        warn_lifespan_int = int(warn_lifespan) if warn_lifespan else 300
    except (ValueError, TypeError):
        warn_lifespan_int = 300
    
    # 计算新的状态
    status_result = blacklist_updater.calculate_new_status(
        bot_id=bot_id,
        group_id=group_id,
        user_id=user_id,
        block_status=block_status,
        warn_count_threshold=warn_count_int,
        warn_lifespan=warn_lifespan_int,
        timestamp=timestamp
    )
    
    new_block_status = status_result["new_block_status"]
    new_block_count = status_result["new_block_count"]
    need_update = status_result["need_update"]
    block_message = status_result["block_message"]
    
    # 如果需要更新数据库
    if need_update:
        # 根据blacklist_cross_group判断更新范围
        if blacklist_cross_group == "enable":
            # 跨群组更新
            update_result = blacklist_updater.update_blacklist_cross_group(
                bot_id=bot_id,
                user_id=user_id,
                new_block_status=new_block_status,
                new_block_count=new_block_count
            )
        else:
            # 仅更新当前群组
            update_result = blacklist_updater.update_blacklist_single_group(
                bot_id=bot_id,
                group_id=group_id,
                user_id=user_id,
                new_block_status=new_block_status,
                new_block_count=new_block_count
            )
        
        matched_count = update_result["matched_count"]
        modified_count = update_result["modified_count"]
    else:
        matched_count = 0
        modified_count = 0
    
    # 返回结果
    return {
        "new_block_status": new_block_status,
        "block_count": new_block_count,
        "block_message": block_message,
        "matched_count": matched_count,
        "modified_count": modified_count
    }
