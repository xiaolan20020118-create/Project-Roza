# sync_configs_to_mongo 使用说明

交互式脚本，批量读取指定目录下的 bot 或 group YAML 配置，并写入 MongoDB（upsert）。

## 依赖
- Python 3.12（或兼容版本）
- pymongo

安装依赖：
```bash
pip install pymongo
```

## 运行
在项目根目录执行：
```bash
python sync_configs_to_mongo.py
```
按提示交互：
1) 输入 Mongo URL（默认 `mongodb://localhost:27017`）
2) 输入数据库名（默认 `roza_database`）
3) 选择录入类型：`bot` 或 `group`（默认 `bot`）
4) 输入集合名（Bot 默认 `bot_config`，Group 默认 `group_config`）
5) 输入对应配置目录路径，脚本会递归扫描目录下的 `.yml` / `.yaml` 文件并写入。

## YAML 格式
- 推荐：显式键
  ```yaml
  - bot_id: "1753584528"
    group_id: "0000"  # 默认群请使用 0000（替代 legacy 的 default）
    group_info: "..."
    ...
  ```
- 兼容：legacy `search_key: "bot_id:group_id"` 仍可解析，但已不推荐。

## 文件编码
优先按 UTF-8 读取，若失败则回退到 GB18030。

## 日志输出
命令行会显示：
- 每个文件的处理结果与条数（bot: 统计有 `bot_id` 的单元；group: 统计有 `bot_id` + `group_id` 的单元）
- 失败文件的错误信息

## 常见问题
- 如果有第三方 `bson` 包与 `pymongo` 自带的 bson 冲突，建议卸载独立的 `bson` 包：
  ```bash
  pip uninstall -y bson
  ```
- 确认 Mongo URL、数据库名、集合名填写正确。