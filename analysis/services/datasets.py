import threading

from pathlib import Path

import duckdb
from django.db.models import Q

from chat.models import ChatFile, Message


class DatasetService:
    MAX_ROWS = 50
    QUERY_TIMEOUT_SECONDS = 10
    SUPERUSER_ONLY_COLUMNS = ("salaries", "overtime", "other_salaries", "total_salary", "retirement",
                              "health_and_dental", "other_benefits", "total_benefits", "total_compensation")
    RECENT_ONLY_YEARS = 2
    PERIOD_DATE_COLUMNS = ("date", "pay_date", "period_date")
    PERIOD_YEAR_COLUMNS = ("year", "fiscal_year", "calendar_year")

    # Add quote to table name for SQL
    @staticmethod
    def quote(identifier):
        return '"' + identifier.replace('"', '""') + '"'

    @staticmethod
    def reader(path):
        return "read_xlsx" if Path(path).suffix.lower() == ".xlsx" else "read_csv"

    @classmethod
    def column_types(cls, connection, path):
        rows = connection.execute(f"DESCRIBE SELECT * FROM {cls.reader(path)}(?)", [path]).fetchall()
        return [(row[0], row[1]) for row in rows]

    @classmethod
    def describe(cls, message):
        connection = duckdb.connect()
        try:
            with ChatFile.download(message.attachment) as path:
                return cls.column_types(connection, path)
        finally:
            connection.close()

    @classmethod
    def is_readable(cls, path):
        connection = duckdb.connect()
        try:
            return bool(cls.column_types(connection, path))
        except Exception:
            return False
        finally:
            connection.close()

    @staticmethod
    def for_chat(chat):
        if chat is None:
            return []
        is_dataset = Q()
        for extension in Message.DATASET_EXTENSIONS:
            is_dataset |= Q(attachment__iendswith=extension)
        return list(Message.objects.visible().filter(is_dataset, chat=chat).order_by("id"))

    @classmethod
    def period_column(cls, names):
        for name in cls.PERIOD_DATE_COLUMNS:
            if name in names:
                return name, "date"
        for name in cls.PERIOD_YEAR_COLUMNS:
            if name in names:
                return name, "year"
        return None, None

    @classmethod
    def sensitive_columns(cls, names):
        return [name for name in names if name in cls.SUPERUSER_ONLY_COLUMNS]

    @classmethod
    def hidden_columns(cls, names, user):
        sensitive = cls.sensitive_columns(names)
        if cls.period_column(names)[0] is None:
            return sensitive
        if getattr(user, "is_superuser", False):
            return []
        return sensitive

    @classmethod
    def recent_filter(cls, names):
        name, kind = cls.period_column(names)
        if name is None:
            return ""
        if kind == "date":
            return f"TRY_CAST({cls.quote(name)} AS DATE) >= current_date - INTERVAL {cls.RECENT_ONLY_YEARS} YEARS"
        return f"TRY_CAST({cls.quote(name)} AS INTEGER) >= year(current_date) - {cls.RECENT_ONLY_YEARS}"

    @classmethod
    def guard_notes(cls, names, hidden):
        notes = []
        name, kind = cls.period_column(names)
        if hidden and name is None:
            notes.append("These columns are hidden for everyone, because this file has no date or year column "
                         f"to enforce the {cls.RECENT_ONLY_YEARS}-year limit: " + ", ".join(hidden))
        elif hidden:
            notes.append("These columns are hidden for this user, only superusers can see them: " + ", ".join(hidden))
        if kind == "date":
            notes.append(f'Only rows where "{name}" is within the last {cls.RECENT_ONLY_YEARS} years from today '
                         "are available, older rows cannot be queried")
        elif kind == "year":
            notes.append(f'Only rows where "{name}" is the current year or one of the previous {cls.RECENT_ONLY_YEARS} '
                         "years are available, older years cannot be queried")
        return notes

    @classmethod
    def load_for_user(cls, connection, message, user):
        with ChatFile.download(message.attachment) as path:
            cls.load_table(connection, message, user, path)

    @classmethod
    def load_table(cls, connection, message, user, path):
        names = [name for name, _ in cls.column_types(connection, path)]
        select = "*"
        hidden = cls.hidden_columns(names, user)
        if hidden:
            select += " EXCLUDE (" + ", ".join(cls.quote(name) for name in hidden) + ")"
        recent = cls.recent_filter(names)
        where = f" WHERE {recent}" if recent else ""
        connection.execute(
            f"CREATE TABLE {cls.quote(message.table_name)} AS SELECT {select} FROM {cls.reader(path)}(?){where}",
            [path],
        )

    @staticmethod
    def lock(connection):
        connection.execute("SET enable_external_access = false")
        connection.execute("SET lock_configuration = true")

    @classmethod
    def run_query(cls, messages, sql, user, max_rows=None):
        max_rows = max_rows or cls.MAX_ROWS
        connection = duckdb.connect()
        timer = threading.Timer(cls.QUERY_TIMEOUT_SECONDS, connection.interrupt)
        try:
            for message in messages:
                try:
                    cls.load_for_user(connection, message, user)
                except Exception:
                    continue
            cls.lock(connection)
            timer.start()
            cursor = connection.execute(sql)
            if cursor.description is None:
                return {"columns": [], "rows": [], "truncated": False}
            rows = cursor.fetchmany(max_rows + 1)
            return {
                "columns": [column[0] for column in cursor.description],
                "rows": rows[:max_rows],
                "truncated": len(rows) > max_rows,
            }
        finally:
            timer.cancel()
            connection.close()
