"""User authentication and role management."""

import os
import re
from dataclasses import dataclass

from dotenv import dotenv_values

USER_PATTERN = re.compile(r"^APP_USER_(\d+)_(.+)$")


@dataclass
class UserConfig:
    name: str
    password: str
    role: str  # "admin" or "user"


class UserManager:
    def __init__(self, env_path: str = ".env"):
        self._env_path = env_path
        self._users: dict[str, UserConfig] = {}
        self._load()

    def _load(self):
        self._users.clear()
        if not os.path.exists(self._env_path):
            return

        values = dotenv_values(self._env_path)
        indices: dict[int, dict[str, str]] = {}

        for key, val in values.items():
            m = USER_PATTERN.match(key)
            if m:
                idx = int(m.group(1))
                field_name = m.group(2)
                indices.setdefault(idx, {})[field_name] = val or ""

        for idx in sorted(indices):
            data = indices[idx]
            name = data.get("NAME", "")
            if not name:
                continue
            self._users[name] = UserConfig(
                name=name,
                password=data.get("PASSWORD", ""),
                role=data.get("ROLE", "user"),
            )

    def authenticate(self, username: str, password: str) -> UserConfig | None:
        user = self._users.get(username)
        if user and user.password == password:
            return user
        return None

    def list_users(self) -> list[UserConfig]:
        return list(self._users.values())

    def is_admin(self, username: str) -> bool:
        user = self._users.get(username)
        return user is not None and user.role == "admin"
