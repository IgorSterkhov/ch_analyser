import os
import re
from dataclasses import dataclass, field
from dotenv import dotenv_values

from ch_analyser.logging_config import get_logger

logger = get_logger(__name__)

CONN_PREFIX = "CLICKHOUSE_CONNECTION_"
CONN_PATTERN = re.compile(r"^CLICKHOUSE_CONNECTION_(\d+)_(.+)$")
FIELDS = ("NAME", "HOST", "PORT", "USER", "PASSWORD", "DATABASE")


@dataclass
class ConnectionConfig:
    name: str
    host: str
    port: int = 9000
    user: str = "default"
    password: str = ""
    database: str = "default"


class ConnectionManager:
    def __init__(self, env_path: str = ".env"):
        self._env_path = env_path
        self._connections: dict[int, ConnectionConfig] = {}
        self._load()

    def _load(self):
        self._connections.clear()
        if not os.path.exists(self._env_path):
            return

        values = dotenv_values(self._env_path)
        indices: dict[int, dict[str, str]] = {}

        for key, val in values.items():
            m = CONN_PATTERN.match(key)
            if m:
                idx = int(m.group(1))
                field_name = m.group(2)
                indices.setdefault(idx, {})[field_name] = val or ""

        for idx in sorted(indices):
            data = indices[idx]
            if "NAME" not in data or "HOST" not in data:
                continue
            self._connections[idx] = ConnectionConfig(
                name=data.get("NAME", ""),
                host=data.get("HOST", "localhost"),
                port=int(data.get("PORT", "9000")),
                user=data.get("USER", "default"),
                password=data.get("PASSWORD", ""),
                database=data.get("DATABASE", "default"),
            )

    def list_connections(self) -> list[ConnectionConfig]:
        return [self._connections[k] for k in sorted(self._connections)]

    def get_connection(self, name: str) -> ConnectionConfig | None:
        for cfg in self._connections.values():
            if cfg.name == name:
                return cfg
        return None

    def add_connection(self, cfg: ConnectionConfig):
        next_idx = max(self._connections.keys(), default=0) + 1
        self._connections[next_idx] = cfg
        self._persist()
        logger.info("Added connection: %s", cfg.name)

    def update_connection(self, old_name: str, cfg: ConnectionConfig):
        for idx, existing in self._connections.items():
            if existing.name == old_name:
                self._connections[idx] = cfg
                self._persist()
                logger.info("Updated connection: %s -> %s", old_name, cfg.name)
                return
        raise ValueError(f"Connection '{old_name}' not found")

    def delete_connection(self, name: str):
        for idx, existing in list(self._connections.items()):
            if existing.name == name:
                del self._connections[idx]
                self._persist()
                logger.info("Deleted connection: %s", name)
                return
        raise ValueError(f"Connection '{name}' not found")

    def _persist(self):
        # Read existing non-CLICKHOUSE lines
        other_lines = []
        if os.path.exists(self._env_path):
            with open(self._env_path, "r") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#") and CONN_PATTERN.match(stripped.split("=")[0]):
                        continue
                    other_lines.append(line)

        # Reindex connections starting from 1
        reindexed: dict[int, ConnectionConfig] = {}
        for new_idx, cfg in enumerate(
            (self._connections[k] for k in sorted(self._connections)), start=1
        ):
            reindexed[new_idx] = cfg
        self._connections = reindexed

        with open(self._env_path, "w") as f:
            for line in other_lines:
                f.write(line)

            for idx, cfg in sorted(self._connections.items()):
                prefix = f"{CONN_PREFIX}{idx}_"
                f.write(f"{prefix}NAME={cfg.name}\n")
                f.write(f"{prefix}HOST={cfg.host}\n")
                f.write(f"{prefix}PORT={cfg.port}\n")
                f.write(f"{prefix}USER={cfg.user}\n")
                f.write(f"{prefix}PASSWORD={cfg.password}\n")
                f.write(f"{prefix}DATABASE={cfg.database}\n")
