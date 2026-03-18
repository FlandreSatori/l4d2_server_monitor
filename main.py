from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from typing import Any

import a2s

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register


@register(
    "astrbot_plugin_l4d2_server_monitor",
    "FlandreSatori",
    "L4D2 服务器监控与地图记录插件",
    "1.1.1",
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

    @staticmethod
    def _invoke_a2s_func(func, address: tuple[str, int]):
        try:
            return func(address, timeout=10.0, encoding="utf-8")
        except TypeError:
            try:
                return func(address, timeout=10.0)
            except TypeError:
                return func(address)

    @staticmethod
    def _list_callable_names() -> list[str]:
        names: list[str] = []
        for name in dir(a2s):
            try:
                if name.startswith("_"):
                    continue
                attr = getattr(a2s, name)
                if callable(attr):
                    names.append(name)
            except Exception:
                continue
        return names

    async def _resolve_by_module_function(
        self,
        address: tuple[str, int],
        kind: str,
    ):
        candidate_names = [kind, f"a{kind}", f"get_{kind}", f"query_{kind}"]
        for name in candidate_names:
            query_func = getattr(a2s, name, None)
            if not callable(query_func):
                continue

            if asyncio.iscoroutinefunction(query_func):
                return await asyncio.wait_for(
                    self._invoke_a2s_func(query_func, address),
                    timeout=10.0,
                )

            loop = asyncio.get_running_loop()
            return await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self._invoke_a2s_func(query_func, address),
                ),
                timeout=10.0,
            )

        return None

    @staticmethod
    def _build_client_instance(address: tuple[str, int]):
        host, port = address
        class_names = ["A2S", "ServerQuerier", "Client", "Query"]
        for class_name in class_names:
            cls = getattr(a2s, class_name, None)
            if not callable(cls):
                continue
            cls_obj: Any = cls
            constructors = [
                ((address,), {"timeout": 10.0}),
                ((address,), {}),
                ((host, port), {"timeout": 10.0}),
                ((host, port), {}),
                ((), {"host": host, "port": port, "timeout": 10.0}),
                ((), {"host": host, "port": port}),
            ]
            for args, kwargs in constructors:
                try:
                    return cls_obj(*args, **kwargs)
                except Exception:
                    continue
        return None

    async def _resolve_by_client_object(
        self,
        address: tuple[str, int],
        kind: str,
    ):
        client = self._build_client_instance(address)
        if client is None:
            return None

        method_names = [kind, f"a{kind}", f"get_{kind}", f"query_{kind}"]
        for method_name in method_names:
            method = getattr(client, method_name, None)
            if not callable(method):
                continue

            try:
                result = method(timeout=10.0, encoding="utf-8")
            except TypeError:
                try:
                    result = method(timeout=10.0)
                except TypeError:
                    result = method()

            if inspect.isawaitable(result):
                return await asyncio.wait_for(result, timeout=10.0)

            loop = asyncio.get_running_loop()
            return await asyncio.wait_for(
                loop.run_in_executor(None, lambda: result),
                timeout=10.0,
            )

        return None

    async def _query_a2s(self, address: tuple[str, int], kind: str):
        data = await self._resolve_by_module_function(address, kind)
        if data is not None:
            return data

        data = await self._resolve_by_client_object(address, kind)
        if data is not None:
            return data

        callables = ", ".join(self._list_callable_names()[:30])
        module_file = getattr(a2s, "__file__", "unknown")
        raise RuntimeError(
            f"a2s query method not found for '{kind}'. module={module_file}, callables=[{callables}]",
        )

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
    async def maps_command(self, event: AstrMessageEvent, map_parts: str = ""):
        """查看或追加今日地图。用法：/map [地图名]"""
        new_map = map_parts.strip()
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

        try:
            info: Any = await self._query_a2s(address, "info")

            try:
                players_data: Any = await self._query_a2s(address, "players")
            except Exception as exc:
                logger.warning(f"Failed to query L4D2 players: {exc!s}")
                players_data = []

            server_name = getattr(info, "server_name", "Unknown")
            map_name = getattr(info, "map_name", "Unknown")
            player_count = getattr(info, "player_count", "?")
            max_players = getattr(info, "max_players", "?")

            server_info = [
                f"|====={server_name}=====|",
                f"地图: {map_name}",
                f"玩家: {player_count}/{max_players}",
            ]

            players = players_data if isinstance(players_data, list) else []
            if players:
                server_info.append("")
                server_info.append("在线玩家:")
                for player in players:
                    name = str(getattr(player, "name", "")).strip()
                    if not name:
                        continue
                    duration = int(getattr(player, "duration", 0))
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
