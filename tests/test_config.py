import os
import tempfile
import pytest

from ch_analyser.config import ConnectionConfig, ConnectionManager


@pytest.fixture
def env_file(tmp_path):
    return str(tmp_path / ".env")


@pytest.fixture
def manager(env_file):
    return ConnectionManager(env_path=env_file)


@pytest.fixture
def sample_cfg():
    return ConnectionConfig(
        name="Test",
        host="localhost",
        port=9000,
        user="default",
        password="secret",
        database="test_db",
    )


class TestConnectionConfig:
    def test_defaults(self):
        cfg = ConnectionConfig(name="A", host="host1")
        assert cfg.port == 9000
        assert cfg.user == "default"
        assert cfg.password == ""
        assert cfg.database == "default"


class TestConnectionManager:
    def test_empty_file(self, manager):
        assert manager.list_connections() == []

    def test_add_and_list(self, manager, sample_cfg):
        manager.add_connection(sample_cfg)
        conns = manager.list_connections()
        assert len(conns) == 1
        assert conns[0].name == "Test"
        assert conns[0].host == "localhost"
        assert conns[0].password == "secret"

    def test_get_connection(self, manager, sample_cfg):
        manager.add_connection(sample_cfg)
        cfg = manager.get_connection("Test")
        assert cfg is not None
        assert cfg.host == "localhost"

    def test_get_connection_not_found(self, manager):
        assert manager.get_connection("nonexistent") is None

    def test_update_connection(self, manager, sample_cfg):
        manager.add_connection(sample_cfg)
        updated = ConnectionConfig(
            name="TestUpdated",
            host="remotehost",
            port=9001,
            user="admin",
            password="newpass",
            database="prod",
        )
        manager.update_connection("Test", updated)
        conns = manager.list_connections()
        assert len(conns) == 1
        assert conns[0].name == "TestUpdated"
        assert conns[0].host == "remotehost"

    def test_update_not_found(self, manager, sample_cfg):
        with pytest.raises(ValueError):
            manager.update_connection("nonexistent", sample_cfg)

    def test_delete_connection(self, manager, sample_cfg):
        manager.add_connection(sample_cfg)
        manager.delete_connection("Test")
        assert manager.list_connections() == []

    def test_delete_not_found(self, manager):
        with pytest.raises(ValueError):
            manager.delete_connection("nonexistent")

    def test_persistence(self, env_file, sample_cfg):
        m1 = ConnectionManager(env_path=env_file)
        m1.add_connection(sample_cfg)

        m2 = ConnectionManager(env_path=env_file)
        conns = m2.list_connections()
        assert len(conns) == 1
        assert conns[0].name == "Test"
        assert conns[0].password == "secret"

    def test_multiple_connections(self, manager):
        for i in range(3):
            manager.add_connection(ConnectionConfig(
                name=f"Conn{i}",
                host=f"host{i}",
            ))
        conns = manager.list_connections()
        assert len(conns) == 3
        assert [c.name for c in conns] == ["Conn0", "Conn1", "Conn2"]

    def test_reindex_after_delete(self, env_file):
        m = ConnectionManager(env_path=env_file)
        for i in range(3):
            m.add_connection(ConnectionConfig(name=f"C{i}", host=f"h{i}"))
        m.delete_connection("C1")

        # Reload and verify reindexed
        m2 = ConnectionManager(env_path=env_file)
        conns = m2.list_connections()
        assert len(conns) == 2
        assert conns[0].name == "C0"
        assert conns[1].name == "C2"

    def test_preserves_other_env_vars(self, env_file, sample_cfg):
        with open(env_file, "w") as f:
            f.write("OTHER_VAR=hello\n")
            f.write("ANOTHER=world\n")

        m = ConnectionManager(env_path=env_file)
        m.add_connection(sample_cfg)

        with open(env_file) as f:
            content = f.read()
        assert "OTHER_VAR=hello" in content
        assert "ANOTHER=world" in content
        assert "CLICKHOUSE_CONNECTION_1_NAME=Test" in content


class TestIntegrationClient:
    @pytest.mark.integration
    def test_connect(self):
        from ch_analyser.client import CHClient
        cfg = ConnectionConfig(
            name="Local",
            host="localhost",
            port=9000,
            user="default",
            password="",
            database="test_db",
        )
        client = CHClient(cfg)
        client.connect()
        assert client.connected
        result = client.execute("SELECT 1 AS val")
        assert result == [{"val": 1}]
        client.disconnect()
        assert not client.connected


class TestIntegrationServices:
    @pytest.mark.integration
    def test_get_tables(self):
        from ch_analyser.client import CHClient
        from ch_analyser.services import AnalysisService
        cfg = ConnectionConfig(
            name="Local",
            host="localhost",
            port=9000,
            user="default",
            password="",
            database="test_db",
        )
        client = CHClient(cfg)
        client.connect()
        service = AnalysisService(client)

        tables = service.get_tables()
        table_names = [t["name"] for t in tables]
        assert "events" in table_names
        assert "users" in table_names
        assert "metrics" in table_names

        for name in ["events", "users", "metrics"]:
            t = next(x for x in tables if x["name"] == name)
            assert "size" in t
            assert t["size"] != "0 B"

        client.disconnect()

    @pytest.mark.integration
    def test_get_columns(self):
        from ch_analyser.client import CHClient
        from ch_analyser.services import AnalysisService
        cfg = ConnectionConfig(
            name="Local",
            host="localhost",
            port=9000,
            user="default",
            password="",
            database="test_db",
        )
        client = CHClient(cfg)
        client.connect()
        service = AnalysisService(client)

        columns = service.get_columns("events")
        col_names = [c["name"] for c in columns]
        assert "id" in col_names
        assert "event_date" in col_names
        assert "event_type" in col_names

        for c in columns:
            assert "type" in c
            assert "codec" in c
            assert "size" in c

        client.disconnect()
