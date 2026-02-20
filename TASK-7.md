1. надо проверить расчет Refs в таблице таблиц. К примеру есть такой кейс: 
- таблица core_wh.srid_tracker
- Refs = 1, и при нажатии выдает "core_wh.srid_tracker_to_shk_gp_mv"
- DDL core_wh.srid_tracker_to_shk_gp_mv : 
```
CREATE MATERIALIZED VIEW core_wh.srid_tracker_to_shk_gp_mv TO core_wh.shk_event_log_gp
(
    `rid` Int64,
    `wh_rid` Int64,
    `srid` String,
    `shk_id` Int64,
    `action_id` UInt8,
    `ts` DateTime,
    `dt` Date,
    `office_id` Int32,
    `place_cod` Nullable(Int32),
    `waysheet_id` Nullable(Int32),
    `dst_office_id` Nullable(Int32),
    `create_dt` Nullable(DateTime),
    `sm_id` Nullable(Int8),
    `src_office_id` Nullable(Int32),
    `first_date` Nullable(DateTime),
    `employee_id` Nullable(Int32),
    `transfer_box_id` Nullable(Int64),
    `box_type` Nullable(Int8),
    `container_id` Nullable(Int64),
    `kafka_tracker_id` Int32,
    `source` LowCardinality(Nullable(String)),
    `ext` String,
    `ip` LowCardinality(Nullable(String)),
    `kafka_key` Int64,
    `_kafka_offset` UInt64,
    `_kafka_timestamp` DateTime,
    `_kafka_partition` UInt8,
    `row_created` DateTime,
    `_row_created` DateTime
)
AS SELECT
    toInt64(halfMD5(srid)) AS rid,
    toInt64(0) AS wh_rid,
    srid,
    coalesce(shk_id, 0) AS shk_id,
    multiIf(action_id IN (310, 640), 35, 0) AS action_id,
    ts,
    toDate(ts) AS dt,
    office_id,
    toInt32(place_cod) AS place_cod,
    waysheet_id,
    next_office_id AS dst_office_id,
    parseDateTimeBestEffortOrNull(JSONExtractString(ext, 'create_dt')) AS create_dt,
    sm_id,
    JSONExtract(ext, 'srcofficeid', 'Nullable(Int32)') AS src_office_id,
    parseDateTimeBestEffortOrNull(JSONExtractString(ext, 'first_date')) AS first_date,
    employee_id,
    multiIf(tare_type = 'TBX', tare, NULL) AS transfer_box_id,
    box_type,
    multiIf(tare_type != 'TBX', tare, NULL) AS container_id,
    coalesce(toInt32(_kafka_timestamp), 0) AS kafka_tracker_id,
    _source AS source,
    coalesce(ext, '') AS ext,
    _ip AS ip,
    rid AS kafka_key,
    _kafka_offset,
    coalesce(_kafka_timestamp, now()) AS _kafka_timestamp,
    _kafka_partition,
    nowInBlock() AS row_created,
    _kafka_timestamp AS _row_created
FROM srid_tracker.srid_tracker_prepared
WHERE action_id = 35
SETTINGS max_block_size = 100000
```
почему произошло срабавтывание? 
Доавай починим.
2. Когда я нажимаю на Refs в твблице таблиц, появляется окошко, в котором не работает кнопка Copy, она не копирует в буфер обмена.