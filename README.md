# Roza 指令与配置同步工作流

本项目包含指令系统与配置同步脚本，支持多群组/多智能体的配置管理与数据库同步。本文用纯文字说明核心用法。

## 目录结构速览

- `src/command_system/`：指令系统代码，核心文件 [command_unified.py](src/command_system/command_unified.py)。
- `src/main_workflow/`：工作流主逻辑（上下文、记忆、好感度、画像等）。
- `bot_config/` 与 `group_config/`：待导入 MongoDB 的配置 YAML，`configs/` 子目录存放实际配置文件。
- `README_sync_configs.md`：配置同步脚本的操作说明。

## 指令系统（/Roza.*）

- 入口：调用 [command_unified.py](src/command_system/command_unified.py) 的 `main`（或 `execute_command`）。
- 判定：以空格或行首分隔的 `/Roza.` 视为指令，其余为普通对话；仅管理员可执行，非管理员返回“无管理员权限，无法执行此操作”。
- 动作：`get` / `set` / `clear`；类型：`favor` / `usage` / `memory` / `context` / `persona` / `blacklist`。
- any 模式：`...any` + `bot_id:group_id:user_id`，支持 `%` 通配，跨 bot/group/user 操作。
- 跨群共享开关（入参，默认 disable）：`usage_limit_cross_group`、`persona_cross_group`、`favor_cross_group`、`blacklist_cross_group`。启用后 set/clear 会对同一 bot 下所有群的指定用户（或 all）同步变更；get 不受影响。
- 清理上下文特例：`/Roza.clear.context` 非 any 时，仅删除 `history_entries` 最新 `context_pool_size` 条，不再整表清空。
- 计数：get 的 `modified_count` 为命中文档数；set/clear 为实际修改数。
- 返回（扁平）：`result`、`command_type`、`parameters`、`modified_count`、`logs`、`action`、`type_key`、`field`、`has_any`。
- 日志与汇总：`logs` 逐条记录批处理日志（指令类型、操作计数、指向对象、执行结果）；`result` 为人类可读汇总，可直接返回给上层。

## 消息预处理

- 文件：[src/main_workflow/message_preprocessor.py](../project_Roza_v1.3/src/main_workflow/message_preprocessor.py)。
- 功能：判定是否指令（含 `/Roza.` → `command`，否则 `chat`），生成北京时区时间戳（整数）、日期字段，生成 `commonsense_search_key`，提取 `quoted_message`。

## 配置同步脚本

- 参考 [README_sync_configs.md](README_sync_configs.md)。
- `bot_config/`、`group_config/` 下的 `configs/` 目录存放实际 YAML；`*_standard`/`*_grand` 为模板或默认配置。
- 导入时选择 `configs/` 目录，可一次性批量导入全部 YAML。

## 快速上手

1. 安装依赖（需 pymongo）。
2. 准备 MongoDB 连接字符串 `MONGO_URL`。
3. 同步配置：按 `README_sync_configs.md` 运行导入脚本，将 `bot_config/configs` 与 `group_config/configs` 导入 MongoDB。
4. 将 `roza_maiden_v1.3` 导入 Dify 1.9.2+（使用 Dify 的流程导入功能）。
5. 验证工作流的环境变量是否正确配置。