# 数据库表结构文档

## 集合名称

`user_data` - 用户数据集合

## 索引

| 索引名称 | 字段 | 类型 |
|---------|------|------|
| idx_user_data | bot_id, group_id, user_id | 复合唯一索引 |

## 文档结构

### 索引字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| bot_id | str | 机器人ID |
| group_id | str | 群组ID（`9999` 为跨群模板文档） |
| user_id | str | 用户ID |

### 跨群字段（存储在 9999 模板中）

这些字段根据跨群配置决定是否从模板继承到新群组：

#### favor 相关（受 `favor_cross_group` 影响）

| 字段名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| favor_value | int | 0 | 好感度值 |
| last_favor_change | int | 0 | 最后一次好感度变化量 |

#### persona 相关（受 `persona_cross_group` 影响）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| persona_attributes | dict | 用户画像属性 |
| persona_attributes.basic_info | str | 基本信息 |
| persona_attributes.living_habits | str | 生活习惯 |
| persona_attributes.psychological_traits | str | 心理特征 |
| persona_attributes.interests_preferences | str | 兴趣偏好 |
| persona_attributes.dislikes | str | 反感点 |
| persona_attributes.ai_expectations | str | 对AI的期望 |
| persona_attributes.memory_points | str | 希望记住的信息 |

#### blacklist 相关（受 `blacklist_cross_group` 影响）

| 字段名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| block_status | bool | True | 封禁状态（True=pass, False=block） |
| block_count | int | 0 | 违规计数 |
| last_operate_time | str | ISO格式字符串 | 最后操作时间 |

#### usage 相关中受 `usage_limit_cross_group` 影响的字段

| 字段名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| daily_usage_count | int | 0 | 每日使用量计数（每日重置） |

### 非跨群字段（每个群组独立）

#### memory 相关

| 字段名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| long_term_memory | list | [] | 长期记忆数组 |

#### context 相关

| 字段名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| history_entries | list | [] | 历史对话记录数组 |
| history_stats.total_histories | int | 0 | 总历史条目数 |

#### usage 相关中各群独立的字段

| 字段名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| total_usage | dict | - | 总使用量统计 |
| total_usage.total_chat_count | int | 0 | 总对话次数 |
| total_usage.total_tokens | int | 0 | 总token数 |
| total_usage.total_prompt_token | int | 0 | 总输入token数 |
| total_usage.total_output_token | int | 0 | 总输出token数 |

### 系统字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| created_at | str | 创建时间（ISO格式字符串） |
| updated_at | str | 更新时间（ISO格式字符串） |

## 跨群配置说明

跨群配置通过 `integrated_workflow.py` 中的 `set_cross_group_config()` 方法设置：

| 配置项 | 类型 | 说明 |
|--------|------|------|
| favor_cross_group | bool | 好感度是否跨群 |
| persona_cross_group | bool | 用户画像是否跨群 |
| blacklist_cross_group | bool | 黑名单是否跨群 |
| usage_limit_cross_group | bool | 用量统计是否跨群 |

当用户首次进入新群组时，系统会根据这些配置决定是否从 `group_id=9999` 的模板文档继承相应字段。
