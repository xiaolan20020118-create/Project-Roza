import pymongo
from datetime import datetime
import re
from typing import Dict, Any


class MongoDBSystem:
    """统一的MongoDB系统 - 管理所有数据库操作

    注意: 索引由 integrated_workflow.py 统一创建，此处不再重复创建
    """

    def __init__(self, mongo_url: str, db_name: str = "roza_database"):
        self.client = pymongo.MongoClient(mongo_url)
        self.db = self.client[db_name]
        self.collection = self.db["user_data"]


class FavorUpdater:
    """好感度更新器 - 核心业务逻辑"""
    
    def __init__(self, mongo_system: MongoDBSystem):
        self.mongo_system = mongo_system
    
    def calculate_favor_change(self, favor_judge: str) -> int:
        """
        计算好感度变化值
        从favor_judge字符串中提取0-9的数字，计算平均值，然后减去基准值4
        """
        # 使用正则表达式提取字符串中的所有数字
        numbers_str = re.findall(r'\d+', favor_judge)
        
        # 将提取的字符串数字转换为整数
        numbers = []
        for num_str in numbers_str:
            try:
                num = int(num_str)
                numbers.append(num)
            except ValueError:
                continue
        
        # 过滤数字，只保留0到9范围内的数字
        filtered_numbers = [num for num in numbers if 0 <= num <= 9]
        
        # 计算平均值，避免除零错误
        if len(filtered_numbers) > 0:
            avg = sum(filtered_numbers) / len(filtered_numbers)
            avg = int(avg)
        else:
            avg = 4  # 如果没有有效数字，默认为4（基准值）
        
        # 计算好感度变化：平均值 - 基准值4
        favor_change = avg - 4
        
        return favor_change
    
    def update_favor_single_group(self, bot_id: str, group_id: str, user_id: str,
                                  new_favor_value: int, favor_change: int) -> Dict[str, Any]:
        """
        更新单个群组的好感度
        
        返回：
        - matched_count: 匹配的文档数
        - modified_count: 修改的文档数
        """
        # 更新favor_value和last_favor_change
        result = self.mongo_system.collection.update_one(
            {
                "bot_id": bot_id,
                "group_id": group_id,
                "user_id": user_id
            },
            {
                "$set": {
                    "favor_value": new_favor_value,
                    "last_favor_change": favor_change,
                    "updated_at": datetime.utcnow().isoformat()
                }
            },
            upsert=True
        )
        
        return {
            "matched_count": result.matched_count,
            "modified_count": result.modified_count
        }
    
    def update_favor_cross_group(self, bot_id: str, user_id: str,
                                 new_favor_value: int, favor_change: int) -> Dict[str, Any]:
        """
        跨群组更新好感度
        更新所有bot_id相同且user_id相同的文档（包括9999模板文档）

        返回：
        - matched_count: 匹配的文档数
        - modified_count: 修改的文档数
        """
        # 更新所有符合条件的文档（包括9999模板）
        result = self.mongo_system.collection.update_many(
            {
                "bot_id": bot_id,
                "user_id": user_id
            },
            {
                "$set": {
                    "favor_value": new_favor_value,
                    "last_favor_change": favor_change,
                    "updated_at": datetime.utcnow().isoformat()
                }
            }
        )

        return {
            "matched_count": result.matched_count,
            "modified_count": result.modified_count
        }


def main(
    favor_cross_group: Any,
    favor_judge: str,
    bot_id: str,
    group_id: str,
    user_id: str,
    favor_value: int,
    MONGO_URL: str
) -> Dict[str, Any]:
    """
    好感度更新主函数

    参数：
    - favor_cross_group: 是否跨群组更新（整型 1/0）
    - favor_judge: 好感度判断字符串（包含0-9的数字）
    - bot_id: 机器人ID
    - group_id: 群组ID
    - user_id: 用户ID
    - favor_value: 当前好感度值（从主工作流传入，避免重复查询）
    - MONGO_URL: MongoDB连接URL

    返回：
    - favor_change: 本次好感度变化量（带符号）
    - new_favor_value: 更新后的好感度值
    - favor_cross_group: 跨群配置输出（整型 1/0）
    - matched_count: 匹配的文档数量
    - modified_count: 修改的文档数量
    """
    
    # 初始化系统
    mongo_system = MongoDBSystem(MONGO_URL)
    favor_updater = FavorUpdater(mongo_system)
    
    # 计算好感度变化
    favor_change = favor_updater.calculate_favor_change(favor_judge)
    
    # 计算新的好感度值
    new_favor_value = favor_value + favor_change
    
    # 根据favor_cross_group判断更新范围
    if favor_cross_group:
        # 跨群组更新
        update_result = favor_updater.update_favor_cross_group(
            bot_id=bot_id,
            user_id=user_id,
            new_favor_value=new_favor_value,
            favor_change=favor_change
        )
    else:
        # 仅更新当前群组
        update_result = favor_updater.update_favor_single_group(
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            new_favor_value=new_favor_value,
            favor_change=favor_change
        )
    
    # 返回结果
    return {
        "favor_change": favor_change,  # type: int
        "new_favor_value": new_favor_value,  # type: int
        "favor_cross_group": 1 if favor_cross_group else 0,  # type: int
        "matched_count": update_result["matched_count"],  # type: int
        "modified_count": update_result["modified_count"]  # type: int
    }
