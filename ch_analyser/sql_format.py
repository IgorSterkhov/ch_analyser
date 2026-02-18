"""ClickHouse-aware SQL formatter.

Uses sqlparse for indentation/structure, then restores correct casing
for ClickHouse-specific functions (camelCase) that sqlparse uppercases.
"""

import re

import sqlparse

# ClickHouse functions with correct casing (camelCase)
CLICKHOUSE_FUNCTIONS = [
    # Dict functions
    "dictGet", "dictGetOrDefault", "dictGetOrNull", "dictHas",
    "dictGetHierarchy", "dictIsIn",
    # Conditional
    "multiIf",
    # Date/time
    "toDate", "toDateTime", "toDateTime64", "toDateOrNull", "toDateTimeOrNull",
    "toStartOfDay", "toStartOfHour", "toStartOfMinute", "toStartOfMonth",
    "toStartOfQuarter", "toStartOfYear", "toStartOfWeek", "toMonday",
    "toYear", "toMonth", "toWeek", "toDayOfMonth", "toDayOfWeek", "toDayOfYear",
    "toHour", "toMinute", "toSecond", "toUnixTimestamp",
    "formatDateTime", "parseDateTimeBestEffort", "parseDateTime64BestEffort",
    "dateDiff", "dateAdd", "dateSub", "timeSlot",
    # Type conversion
    "toString", "toInt8", "toInt16", "toInt32", "toInt64", "toInt128", "toInt256",
    "toUInt8", "toUInt16", "toUInt32", "toUInt64", "toUInt128", "toUInt256",
    "toFloat32", "toFloat64", "toDecimal32", "toDecimal64", "toDecimal128",
    "toFixedString", "toUUID", "toIPv4", "toIPv6",
    "toIntervalSecond", "toIntervalMinute", "toIntervalHour", "toIntervalDay",
    "toIntervalWeek", "toIntervalMonth", "toIntervalQuarter", "toIntervalYear",
    "reinterpretAsInt8", "reinterpretAsInt16", "reinterpretAsInt32", "reinterpretAsInt64",
    "reinterpretAsUInt8", "reinterpretAsUInt16", "reinterpretAsUInt32", "reinterpretAsUInt64",
    "reinterpretAsFloat32", "reinterpretAsFloat64", "reinterpretAsString",
    "accurateCast", "accurateCastOrNull",
    # Aggregate
    "countIf", "sumIf", "avgIf", "minIf", "maxIf", "anyIf",
    "uniq", "uniqExact", "uniqCombined", "uniqCombined64", "uniqHLL12",
    "groupArray", "groupArrayInsertAt", "groupUniqArray",
    "groupBitAnd", "groupBitOr", "groupBitXor",
    "argMin", "argMax",
    "quantile", "quantiles", "quantileExact", "quantileTiming",
    "simpleLinearRegression", "stochasticLinearRegression",
    # String
    "replaceAll", "replaceOne", "replaceRegexpAll", "replaceRegexpOne",
    "splitByChar", "splitByString", "splitByRegexp",
    "arrayStringConcat", "extractAll", "extractAllGroups",
    "trimLeft", "trimRight", "trimBoth",
    "leftPad", "rightPad", "leftPadUTF8", "rightPadUTF8",
    "lowerUTF8", "upperUTF8", "reverseUTF8",
    "substringUTF8", "lengthUTF8", "positionUTF8",
    "positionCaseInsensitive", "positionCaseInsensitiveUTF8",
    "multiSearchFirstIndex", "multiSearchFirstPosition", "multiSearchAny",
    "multiMatchAny", "multiMatchAnyIndex", "multiFuzzyMatchAny",
    "normalizeQuery", "normalizedQueryHash",
    "encodeXMLComponent", "decodeXMLComponent",
    "extractURLParameter", "extractURLParameters", "extractURLParameterNames",
    "cutURLParameter", "cutToFirstSignificantSubdomain",
    "URLHierarchy", "URLPathHierarchy",
    # Array
    "arrayJoin", "arrayConcat", "arrayElement", "arrayPushBack", "arrayPushFront",
    "arrayPopBack", "arrayPopFront", "arraySlice", "arrayReverse",
    "arrayCompact", "arrayDistinct", "arrayEnumerate", "arrayEnumerateDense",
    "arrayEnumerateUniq", "arrayReduce", "arrayReduceInRanges",
    "arrayFilter", "arrayExists", "arrayAll", "arrayFirst", "arrayFirstIndex",
    "arraySum", "arrayAvg", "arrayCount", "arrayMin", "arrayMax",
    "arraySort", "arrayReverseSort", "arrayUniq", "arrayDifference",
    "hasAll", "hasAny", "hasSubstr", "indexOf", "arrayZip",
    # Nullable
    "ifNull", "nullIf", "assumeNotNull", "toNullable", "coalesce", "isNull", "isNotNull",
    # JSON
    "JSONExtract", "JSONExtractString", "JSONExtractInt", "JSONExtractFloat",
    "JSONExtractBool", "JSONExtractRaw", "JSONExtractArrayRaw", "JSONExtractKeysAndValues",
    "JSONHas", "JSONLength", "JSONType", "JSONExtractKeys",
    "simpleJSONExtractString", "simpleJSONExtractInt", "simpleJSONExtractFloat",
    "simpleJSONExtractBool", "simpleJSONExtractRaw", "simpleJSONHas",
    # Bit
    "bitAnd", "bitOr", "bitXor", "bitNot", "bitShiftLeft", "bitShiftRight",
    "bitRotateLeft", "bitRotateRight", "bitTest", "bitTestAll", "bitTestAny",
    "bitCount", "bitPositionsToArray",
    # Hash
    "cityHash64", "sipHash64", "sipHash128", "halfMD5",
    "murmurHash2_32", "murmurHash2_64", "murmurHash3_32", "murmurHash3_64",
    "murmurHash3_128", "xxHash32", "xxHash64", "farmHash64", "javaHash",
    "URLHash",
    # Geo
    "geoDistance", "greatCircleDistance", "greatCircleAngle",
    "pointInEllipses", "pointInPolygon",
    "geohashEncode", "geohashDecode", "geohashesInBox",
    "h3IsValid", "h3GetResolution", "h3EdgeAngle", "h3EdgeLengthM",
    # IP
    "IPv4NumToString", "IPv4StringToNum", "IPv4ToIPv6",
    "IPv6NumToString", "IPv6StringToNum",
    "isIPv4String", "isIPv6String",
    # Misc
    "runningDifference", "runningDifferenceStartingWithFirstValue",
    "runningAccumulate",
    "rowNumberInAllBlocks", "rowNumberInBlock",
    "formatRow", "formatRowNoNewline", "formatReadableSize",
    "generateUUIDv4",
    "getMacro", "getSetting",
    "isFinite", "isInfinite", "isNaN",
    "toTypeName", "blockSize", "materialize", "ignore",
    "currentDatabase", "currentUser", "hostName", "uptime", "version",
    "throwIf", "identity",
]

_FUNC_CASE_MAP = {f.lower(): f for f in CLICKHOUSE_FUNCTIONS}


def _restore_function_case(sql: str) -> str:
    """Restore correct casing for ClickHouse functions after keyword uppercasing."""
    def _replace(match):
        name = match.group(1)
        correct = _FUNC_CASE_MAP.get(name.lower())
        if correct:
            return correct + '('
        return match.group(0)

    return re.sub(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', _replace, sql)


def format_clickhouse_sql(sql: str) -> str:
    """Format SQL with sqlparse, then restore ClickHouse function casing."""
    result = sqlparse.format(sql, reindent=True, keyword_case='upper')
    return _restore_function_case(result)
