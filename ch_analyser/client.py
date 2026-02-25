import time
from datetime import date, datetime

from clickhouse_driver import Client as NativeClient
import clickhouse_connect

from ch_analyser.config import ConnectionConfig
from ch_analyser.logging_config import get_logger

logger = get_logger(__name__)


def _escape_value(v):
    """Escape a Python value for safe inline substitution into a ClickHouse SQL query."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        escaped = v.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    if isinstance(v, (date, datetime)):
        return f"'{v}'"
    if isinstance(v, (list, tuple)):
        return "(" + ", ".join(_escape_value(x) for x in v) + ")"
    return str(v)


class CHClient:
    def __init__(self, config: ConnectionConfig):
        self._config = config
        self._native_client: NativeClient | None = None
        self._http_client = None  # clickhouse_connect client

    @property
    def _use_http(self) -> bool:
        return self._config.protocol == "http"

    def connect(self):
        logger.info(
            "Connecting to %s:%s (protocol=%s, secure=%s) ...",
            self._config.host, self._config.port,
            self._config.protocol, self._config.secure,
        )
        if self._use_http:
            self._connect_http()
        else:
            self._connect_native()
        logger.info("Connected to ClickHouse at %s:%s", self._config.host, self._config.port)

    def _log_params(self, kwargs: dict, label: str):
        """Log connection parameters with password masked."""
        safe = {k: v for k, v in kwargs.items()}
        if "password" in safe:
            safe["password"] = "***" if safe["password"] else "(empty)"
        logger.info("%s params: %s", label, safe)

    def _connect_native(self):
        kwargs = dict(
            host=self._config.host,
            port=self._config.port,
            user=self._config.user,
            password=self._config.password,
            connect_timeout=10,
            send_receive_timeout=30,
        )
        if self._config.secure:
            kwargs["secure"] = True
            if self._config.ca_cert:
                kwargs["ca_certs"] = self._config.ca_cert
        self._log_params(kwargs, "Native connection")
        self._native_client = NativeClient(**kwargs)
        self._native_client.execute("SELECT 1")

    def _connect_http(self):
        kwargs = dict(
            host=self._config.host,
            port=self._config.port,
            username=self._config.user,
            password=self._config.password,
            connect_timeout=10,
            send_receive_timeout=30,
        )
        if self._config.secure:
            kwargs["secure"] = True
            if self._config.ca_cert:
                kwargs["verify"] = True
                kwargs["ca_cert"] = self._config.ca_cert
            else:
                kwargs["verify"] = False
        self._log_params(kwargs, "HTTP connection")
        self._http_client = clickhouse_connect.get_client(**kwargs)
        self._http_client.query("SELECT 1")

    def disconnect(self):
        if self._native_client:
            self._native_client.disconnect()
            self._native_client = None
        if self._http_client:
            self._http_client.close()
            self._http_client = None
        logger.info("Disconnected")

    @property
    def connected(self) -> bool:
        return self._native_client is not None or self._http_client is not None

    def execute(self, query: str, params: dict | None = None,
                max_rows: int | None = None) -> list[dict]:
        if not self.connected:
            raise RuntimeError("Not connected to ClickHouse")
        logger.debug("Executing: %.200s | params=%s", query.strip(), params)
        start = time.monotonic()
        if self._http_client:
            rows = self._execute_http(query, params)
        else:
            rows = self._execute_native(query, params)
        elapsed = time.monotonic() - start
        if max_rows and len(rows) > max_rows:
            logger.warning("Result truncated: %d rows -> %d (max_rows limit)", len(rows), max_rows)
            rows = rows[:max_rows]
        logger.debug("Query OK: %.2fs, %d rows", elapsed, len(rows))
        return rows

    def _execute_native(self, query: str, params: dict | None) -> list[dict]:
        result = self._native_client.execute(query, params or {}, with_column_types=True)
        data, columns = result
        col_names = [c[0] for c in columns]
        return [dict(zip(col_names, row)) for row in data]

    def _execute_http(self, query: str, params: dict | None) -> list[dict]:
        if params:
            escaped = {k: _escape_value(v) for k, v in params.items()}
            query = query % escaped
        result = self._http_client.query(query)
        col_names = result.column_names
        return [dict(zip(col_names, row)) for row in result.result_rows]
