"""SQL Server 数据库工具模块。

该模块提供安全的 SQL Server 数据库查询能力，用于 Text2SQL 技能。
"""

from __future__ import annotations

import json
import os
from typing import Any

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse


class SQLServerExecutor:
    """SQL Server 执行器。

    提供安全的 SQL 查询执行能力，支持连接池和查询超时。
    """

    def __init__(
        self,
        connection_string: str | None = None,
        max_rows: int = 200,
        query_timeout: int = 30,
    ) -> None:
        """初始化执行器。

        参数:
            connection_string: 数据库连接字符串，如果为空则从环境变量读取。
            max_rows: 单次查询返回的最大行数。
            query_timeout: 查询超时时间（秒）。
        """
        self.connection_string = connection_string or os.getenv(
            "SQLSERVER_CONNECTION_STRING",
            "",
        )
        self.max_rows = max_rows
        self.query_timeout = query_timeout
        self._connection_pool: dict[str, Any] = {}

    def _get_connection(self) -> Any:
        """获取数据库连接。

        返回:
            pyodbc.Connection: 数据库连接对象。
        """
        import pyodbc

        return pyodbc.connect(self.connection_string, timeout=10)

    async def execute_query(
        self,
        sql: str,
        max_rows: int | None = None,
    ) -> ToolResponse:
        """执行 SQL 查询并返回结果。

        参数:
            sql: 要执行的 SQL 语句（仅支持 SELECT 查询）。
            max_rows: 覆盖默认的最大行数。

        返回:
            ToolResponse: 包含查询结果的响应。
        """
        # 安全检查：只允许 SELECT 查询
        sql_stripped = sql.strip().upper()
        if not sql_stripped.startswith("SELECT"):
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=json.dumps(
                            {
                                "success": False,
                                "error": "安全限制：仅允许执行 SELECT 查询语句。",
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ],
            )

        if not self.connection_string:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=json.dumps(
                            {
                                "success": False,
                                "error": "数据库连接字符串未配置。请设置环境变量 SQLSERVER_CONNECTION_STRING。",
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ],
            )

        rows_limit = max_rows or self.max_rows

        try:
            import pyodbc
        except ImportError:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=json.dumps(
                            {
                                "success": False,
                                "error": "pyodbc 未安装。请运行: pip install pyodbc",
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ],
            )

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 执行查询
            cursor.execute(sql)

            # 获取列名
            columns = [column[0] for column in cursor.description] if cursor.description else []

            # 获取数据
            rows = cursor.fetchmany(rows_limit)
            has_more = len(rows) == rows_limit

            # 转换为字典列表
            result_data = [dict(zip(columns, row, strict=False)) for row in rows]

            # 处理特殊类型（如 datetime, decimal）
            result_data = self._serialize_data(result_data)

            cursor.close()
            conn.close()

            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=json.dumps(
                            {
                                "success": True,
                                "columns": columns,
                                "row_count": len(result_data),
                                "has_more": has_more,
                                "data": result_data,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ],
            )

        except Exception as exc:
            error_msg = str(exc)
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=json.dumps(
                            {
                                "success": False,
                                "error": f"SQL 执行失败: {error_msg}",
                                "error_type": type(exc).__name__,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ],
            )

    async def get_table_schema(
        self,
        table_name: str,
        schema: str = "dbo",
    ) -> ToolResponse:
        """获取指定表的结构信息。

        参数:
            table_name: 表名。
            schema: 架构名，默认 dbo。

        返回:
            ToolResponse: 包含表结构信息的响应。
        """
        if not self.connection_string:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=json.dumps(
                            {
                                "success": False,
                                "error": "数据库连接字符串未配置。",
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ],
            )

        schema_sql = f"""
        SELECT
            c.column_name,
            c.data_type,
            c.character_maximum_length,
            c.is_nullable,
            c.column_default,
            ep.value AS column_description
        FROM
            INFORMATION_SCHEMA.COLUMNS c
        LEFT JOIN
            sys.extended_properties ep
            ON ep.major_id = OBJECT_ID('{schema}.{table_name}')
            AND ep.minor_id = c.ordinal_position
            AND ep.name = 'MS_Description'
        WHERE
            c.table_schema = '{schema}'
            AND c.table_name = '{table_name}'
        ORDER BY
            c.ordinal_position;
        """

        return await self.execute_query(schema_sql)

    async def list_tables(self, schema: str = "dbo") -> ToolResponse:
        """列出数据库中的所有表。

        参数:
            schema: 架构名，默认 dbo。

        返回:
            ToolResponse: 包含表列表的响应。
        """
        list_sql = f"""
        SELECT
            t.table_name,
            ep.value AS table_description
        FROM
            INFORMATION_SCHEMA.TABLES t
        LEFT JOIN
            sys.extended_properties ep
            ON ep.major_id = OBJECT_ID(t.table_schema + '.' + t.table_name)
            AND ep.minor_id = 0
            AND ep.name = 'MS_Description'
        WHERE
            t.table_schema = '{schema}'
            AND t.table_type = 'BASE TABLE'
        ORDER BY
            t.table_name;
        """

        return await self.execute_query(list_sql)

    def _serialize_data(self, data: list[dict]) -> list[dict]:
        """序列化数据，处理特殊类型。

        参数:
            data: 原始数据列表。

        返回:
            list[dict]: 序列化后的数据列表。
        """
        from datetime import date, datetime
        from decimal import Decimal

        result = []
        for row in data:
            new_row = {}
            for key, value in row.items():
                if isinstance(value, (datetime, date)):
                    new_row[key] = value.isoformat()
                elif isinstance(value, Decimal):
                    new_row[key] = float(value)
                elif isinstance(value, bytes):
                    try:
                        new_row[key] = value.decode("utf-8")
                    except UnicodeDecodeError:
                        new_row[key] = value.decode("gbk", errors="replace")
                elif value is None:
                    new_row[key] = None
                else:
                    new_row[key] = value
            result.append(new_row)
        return result
