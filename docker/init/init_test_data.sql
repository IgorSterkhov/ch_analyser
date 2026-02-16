CREATE DATABASE IF NOT EXISTS test_db;

-- Table 1: events (large, mixed codecs)
CREATE TABLE test_db.events (
    id UInt64 CODEC(Delta, ZSTD),
    event_date Date CODEC(DoubleDelta),
    event_time DateTime CODEC(DoubleDelta),
    user_id UInt32 CODEC(LZ4),
    event_type String CODEC(ZSTD(3)),
    payload String CODEC(ZSTD(1))
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(event_date)
ORDER BY (event_date, user_id, id)
SETTINGS min_bytes_for_wide_part = 0;

-- Table 2: users (small lookup)
CREATE TABLE test_db.users (
    id UInt32 CODEC(Delta, LZ4),
    name String CODEC(ZSTD),
    email String CODEC(ZSTD),
    created_at DateTime CODEC(DoubleDelta)
) ENGINE = MergeTree()
ORDER BY id
SETTINGS min_bytes_for_wide_part = 0;

-- Table 3: metrics (numeric heavy)
CREATE TABLE test_db.metrics (
    ts DateTime CODEC(DoubleDelta),
    host String CODEC(LZ4HC),
    cpu Float64 CODEC(Gorilla),
    memory Float64 CODEC(Gorilla),
    disk_used UInt64 CODEC(Delta, ZSTD)
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(ts)
ORDER BY (host, ts)
SETTINGS min_bytes_for_wide_part = 0;

-- Seed events (100K rows)
INSERT INTO test_db.events
SELECT
    number AS id,
    today() - toIntervalDay(number % 365) AS event_date,
    now() - toIntervalSecond(number * 60) AS event_time,
    number % 10000 AS user_id,
    arrayElement(['click','view','purchase','signup'], (number % 4) + 1) AS event_type,
    repeat('x', number % 200) AS payload
FROM system.numbers LIMIT 100000;

-- Seed users (5K rows)
INSERT INTO test_db.users
SELECT
    number AS id,
    concat('user_', toString(number)) AS name,
    concat('user_', toString(number), '@example.com') AS email,
    now() - toIntervalDay(number % 730) AS created_at
FROM system.numbers LIMIT 5000;

-- Seed metrics (50K rows)
INSERT INTO test_db.metrics
SELECT
    now() - toIntervalSecond(number * 10) AS ts,
    concat('host-', toString(number % 50)) AS host,
    50 + (rand() % 50) AS cpu,
    30 + (rand() % 70) AS memory,
    1000000000 + (rand() % 1000000000) AS disk_used
FROM system.numbers LIMIT 50000;

-- Optimize to merge parts into Wide format
OPTIMIZE TABLE test_db.events FINAL;
OPTIMIZE TABLE test_db.users FINAL;
OPTIMIZE TABLE test_db.metrics FINAL;

-- Generate query_log entries
SELECT count() FROM test_db.events;
SELECT count() FROM test_db.users;
SELECT count() FROM test_db.metrics;
