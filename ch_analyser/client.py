from clickhouse_driver import Client

from ch_analyser.config import ConnectionConfig
from ch_analyser.logging_config import get_logger

logger = get_logger(__name__)


class CHClient:
    def __init__(self, config: ConnectionConfig):
        self._config = config
        self._client: Client | None = None

    def connect(self):
        logger.info("Connecting to %s:%s ...", self._config.host, self._config.port)
        self._client = Client(
            host=self._config.host,
            port=self._config.port,
            user=self._config.user,
            password=self._config.password,
            database=self._config.database,
        )
        self._client.execute("SELECT 1")
        logger.info("Connected to ClickHouse at %s:%s", self._config.host, self._config.port)

    def disconnect(self):
        if self._client:
            self._client.disconnect()
            self._client = None
            logger.info("Disconnected")

    @property
    def connected(self) -> bool:
        return self._client is not None

    def execute(self, query: str, params: dict | None = None) -> list[dict]:
        if not self._client:
            raise RuntimeError("Not connected to ClickHouse")
        result = self._client.execute(query, params or {}, with_column_types=True)
        data, columns = result
        col_names = [c[0] for c in columns]
        return [dict(zip(col_names, row)) for row in data]
