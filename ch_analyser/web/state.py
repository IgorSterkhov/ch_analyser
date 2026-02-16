"""In-memory application state for non-serializable objects."""

from ch_analyser.auth import UserManager
from ch_analyser.config import ConnectionManager

conn_manager: ConnectionManager = ConnectionManager()
user_manager: UserManager = UserManager()

# Active ClickHouse connection objects (not JSON-serializable)
client = None  # CHClient | None
service = None  # AnalysisService | None
active_connection_name: str | None = None
