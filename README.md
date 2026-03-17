# L4D2 Server Monitor

用于 AstrBot 的 L4D2 服务器查询与地图记录插件。

## 功能

- `/有无求生`：查询 L4D2 服务器状态与在线玩家。
- `/map [地图名]`：查看地图列表；带参数时追加一条地图。
- `/reset`：清空地图列表。

## 持久化

地图数据会保存到 AstrBot 数据目录下：

- `data/plugin_data/astrbot_plugin_l4d2_server_monitor/maps.json`

## 依赖

插件目录下包含 `requirements.txt`，安装插件时会自动安装所需第三方库。
