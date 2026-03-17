from __future__ import annotations

import asyncio
import json
from pathlib import Path

import a2s

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register


@register(
    "astrbot_plugin_l4d2_server_monitor",
    "FlandreSatori",
    "L4D2 服务器监控与地图记录插件",
    "1.2.0",
)
class L4D2ServerMonitorPlugin(Star):
    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | None = None,
    ) -> None:
        super().__init__(context, config)
        self.config = config or {}
        self.maps: list[str] = []
        self.bother_count = 0
        self.default_host = "127.0.0.1"
        self.default_port = 27015
        self._data_file: Path = StarTools.get_data_dir() / "maps.json"

    def _get_server_address(self) -> tuple[str, int]:
        host = str(self.config.get("host", self.default_host)).strip()
        if not host:
            host = self.default_host

        raw_port = self.config.get("port", self.default_port)
        try:
            port = int(raw_port)
            if not (1 <= port <= 65535):
                raise ValueError("port out of range")
        except Exception:
            logger.warning(
                f"Invalid plugin config port {raw_port!r}, fallback to {self.default_port}",
            )
            port = self.default_port

        return host, port

    async def initialize(self) -> None:
        await self._load_maps()

    async def terminate(self) -> None:
        await self._save_maps()

    async def _load_maps(self) -> None:
        if not self._data_file.exists():
            self.maps = []
            return

        try:
            data = json.loads(self._data_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self.maps = [str(item).strip() for item in data if str(item).strip()]
            else:
                self.maps = []
        except Exception as exc:
            logger.warning(f"Failed to load map list: {exc!s}")
            self.maps = []

    async def _save_maps(self) -> None:
        try:
            self._data_file.parent.mkdir(parents=True, exist_ok=True)
            self._data_file.write_text(
                json.dumps(self.maps, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error(f"Failed to save map list: {exc!s}")

    def _render_maps(self) -> str:
        if not self.maps:
            return "今日地图列表为空"
        maps_display = "\n".join(
            [f"{index + 1}. {map_name}" for index, map_name in enumerate(self.maps)],
        )
        return f"今日地图列表:\n{maps_display}"

    @filter.command("map")
    async def maps_command(self, event: AstrMessageEvent, *map_parts: str):
        """查看或追加今日地图。用法：/map [地图名]"""
        new_map = " ".join(map_parts).strip()
        if new_map:
            self.maps.append(new_map)
            await self._save_maps()
        yield event.plain_result(self._render_maps())

    @filter.command("下机")
    async def reset_maps(self, event: AstrMessageEvent):
        """重置今日地图列表"""
        self.maps = []
        await self._save_maps()
        yield event.plain_result(self._render_maps())

    @filter.command("有无求生")
    async def l4d2_server(self, event: AstrMessageEvent):
        """查询 L4D2 服务器状态"""
        address = self._get_server_address()
        loop = asyncio.get_running_loop()

        try:
            info = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: a2s.info(address, timeout=10.0, encoding="utf-8"),
                ),
                timeout=10.0,
            )

            try:
                players = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: a2s.players(address, timeout=10.0, encoding="utf-8"),
                    ),
                    timeout=10.0,
                )
            except Exception as exc:
                logger.warning(f"Failed to query L4D2 players: {exc!s}")
                players = []

            server_info = [
                f"|====={info.server_name}=====|",
                f"地图: {info.map_name}",
                f"玩家: {info.player_count}/{info.max_players}",
            ]

            if players:
                server_info.append("")
                server_info.append("在线玩家:")
                for player in players:
                    name = player.name.strip()
                    if not name:
                        continue
                    duration = int(player.duration)
                    hours = duration // 3600
                    minutes = (duration % 3600) // 60
                    time_str = f"{hours}h{minutes}m" if hours > 0 else f"{minutes}m"
                    server_info.append(f"  • {name} ({time_str})")

            server_info.append("")
            server_info.append(self._render_maps())
            yield event.plain_result("\n".join(server_info))
        except Exception as exc:
            logger.error(f"Failed to query L4D2 server: {exc!s}")
            yield event.plain_result(f"❌ 查询失败: {exc!s}")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_empty_mention(self, event: AstrMessageEvent):
        """Reply when the bot is mentioned without any text content."""
        message = event.message_str.strip()

        if message:
            self.bother_count = 0
            return

        if not getattr(event, "is_at_or_wake_command", False):
            return

        reply = "…" if self.bother_count == 0 else "@我又不说话，是不是浅草?"
        self.bother_count += 1
        yield event.plain_result(reply)
