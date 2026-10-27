import re
from django.urls import reverse
from django.utils import timezone
from temporalio.exceptions import WorkflowAlreadyStartedError
from pgvector.django import L2Distance
from scraper.services.client import OllamaClient
from scraper.models import Chunk, Document
from scraper.services.progress import DocumentProgress
from scraper.temporal_workflow.temporal import DocumentWorkflows
from chat.services.chat import ChatService
from analysis.services.datasets import DatasetService
from ddgs import DDGS
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig


@tool
def web_search(query: str) -> str:
    """Search the internet for current information about a topic. Use this when the question needs live or up-to-date facts."""
    results = DDGS().text(query, max_results=5)
    return "\n\n".join(f"{r['title']}: {r['body']}" for r in results)


@tool
def search_documents(query: str, config: RunnableConfig) -> str:
    """Search the user's uploaded documents for information relevant to the query."""
    vendor = config["configurable"]["vendor"]
    qn_vector = OllamaClient().embed(query)
    nearest = (Chunk.objects
        .filter(parent_doc__vendor=vendor, parent_doc__status="completed", is_active=True, parent_doc__is_active=True)
        .order_by(L2Distance("embedding", qn_vector))[:5])
    return "\n\n---\n\n".join(c.content for c in nearest)


@tool
def current_datetime() -> str:
    """Get the current date and time in UTC. Use this for any question about today's date or the time now."""
    return timezone.now().strftime("%Y-%m-%d %H:%M:%S UTC (%A)")


@tool
def list_documents(config: RunnableConfig) -> str:
    """List the documents in this vendor's knowledge base. Use this to say what topics you have information about."""
    vendor = config["configurable"]["vendor"]
    docs = Document.objects.filter(vendor=vendor, is_active=True)
    return "\n".join(f"- {d.url} ({d.source_type}, {d.status})" for d in docs) or "No documents yet."


@tool
def calculator(expression: str) -> str:
    """Work out an arithmetic expression such as "12 * (3 + 4)"."""
    if not re.fullmatch(r"[\d\s+\-*/().]+", expression):
        return "Only numbers and + - * / ( ) are allowed."
    return str(eval(expression))


@tool
def summarize_chat(config: RunnableConfig) -> str:
    """Summarize the current conversation and save it to the chat. Use this when the user asks for a summary or recap of this chat."""
    chat = config["configurable"].get("chat")
    if chat is None:
        return "There is no chat to summarize."
    return ChatService().summarize_chat(chat, chat.user)


class DatasetTools:
    # Graph Types
    CHART_TYPES = ("bar", "line", "pie")
    NO_DATASET = ("No CSV has been uploaded in this chat yet. "
                  "Ask the user to upload one with the clip button next to the message box.")



    @staticmethod
    def chat_files(config):
        return DatasetService.for_chat(config["configurable"].get("chat"))

    @staticmethod
    def user(config):
        chat = config["configurable"].get("chat")
        return chat.user if chat else None

    @staticmethod
    def guard_notes(names, hidden):
        return "".join(f"\nNote: {note}" for note in DatasetService.guard_notes(names, hidden))

    @staticmethod
    def table_summary(message, config, with_types):
        header = f"Table {message.table_name} (file {message.file_label})"
        try:
            columns = DatasetService.describe(message)
        except Exception as error:
            return f"{header}: the file could not be read ({error})"
        names = [name for name, _ in columns]
        hidden = DatasetService.hidden_columns(names, DatasetTools.user(config))
        shown = [(name, kind) for name, kind in columns if name not in hidden]
        if with_types:
            body = "\nColumns:\n" + "\n".join(f'  "{name}" {kind}' for name, kind in shown)
        else:
            body = "\nColumns: " + ", ".join(name for name, _ in shown)
        return header + body + DatasetTools.guard_notes(names, hidden)

    @tool
    def list_datasets(config: RunnableConfig) -> str:
        """List every CSV table uploaded in this chat with its column names. Call this first for any question about data, then pick the table that fits the question, or JOIN tables when the question needs more than one."""
        files = DatasetTools.chat_files(config)
        if not files:
            return DatasetTools.NO_DATASET
        return "\n\n".join(DatasetTools.table_summary(message, config, False) for message in files)

    @tool
    def describe_dataset(table_name: str, config: RunnableConfig) -> str:
        """Show one table's columns with their types. Call this before writing SQL for a table. To see how values are written, run SELECT DISTINCT on a column with query_dataset before filtering on it."""
        files = DatasetTools.chat_files(config)
        if not files:
            return DatasetTools.NO_DATASET
        message = next((m for m in files if m.table_name == table_name), None)
        if message is None:
            return f"No table called {table_name}. This chat's tables are: {', '.join(m.table_name for m in files)}."
        return DatasetTools.table_summary(message, config, True)

    @staticmethod
    def format_result(result):
        lines = [" | ".join(result["columns"])]
        lines += [" | ".join(str(value) for value in row) for row in result["rows"]]
        if result["truncated"]:
            lines.append(f"(only the first {DatasetService.MAX_ROWS} rows are shown)")
        return "\n".join(lines)

    @staticmethod
    def to_number(value):
        return None if value is None else float(value)


    @tool
    def query_dataset(sql: str, config: RunnableConfig) -> str:
        """Run one DuckDB SQL SELECT query over this chat's CSV tables (you can JOIN them) and return the result rows. Use this for every number you report, and to check a column's real values with SELECT DISTINCT ... LIMIT 10 before filtering on them."""
        files = DatasetTools.chat_files(config)
        if not files:
            return DatasetTools.NO_DATASET
        try:
            result = DatasetService.run_query(files, sql, DatasetTools.user(config))
        except Exception as error:
            return f"Error: {error}"
        if not result["rows"]:
            return "The query returned no rows."
        return DatasetTools.format_result(result)

    @tool(response_format="content_and_artifact")
    def make_chart(sql: str, chart_type: str, title: str, config: RunnableConfig) -> tuple[str, dict]:
        """Draw a chart for the user from one DuckDB SQL SELECT query. The query must return exactly two columns: first the label of each bar, point or slice, second its number. chart_type is bar, line or pie. Use this whenever the user asks for a chart, graph or plot."""
        if chart_type not in DatasetTools.CHART_TYPES:
            return f"Error: chart_type must be one of {', '.join(DatasetTools.CHART_TYPES)}.", None
        files = DatasetTools.chat_files(config)
        if not files:
            return DatasetTools.NO_DATASET, None
        try:
            result = DatasetService.run_query(files, sql, DatasetTools.user(config))
            if len(result["columns"]) != 2:
                return "Error: the query must return exactly two columns, a label and a number.", None
            values = [DatasetTools.to_number(row[1]) for row in result["rows"]]
        except Exception as error:
            return f"Error: {error}", None
        if not result["rows"]:
            return "The query returned no rows, so no chart was drawn.", None
        chart = {
            "kind": "chart",
            "type": chart_type,
            "title": title,
            "label": result["columns"][1],
            "labels": [str(row[0]) for row in result["rows"]],
            "values": values,
        }
        return "The chart is shown to the user. It contains:\n" + DatasetTools.format_result(result), chart


class DocumentTools:
    MAX_ROWS = 50
    RUNNING_STATUSES = ("queued", "waiting", "extracting", "embedding")

    # Make details of the artifact shoin details
    @staticmethod
    def card(title, docs, truncated=False):
        rows = []
        for doc in docs:
            if not doc.workflow_run_id:
                last_run = "Never run"
            elif doc.status == "error":
                last_run = "Failed"
            elif doc.status == "pending":
                last_run = "Canceled"
            elif doc.status == "completed":
                last_run = "Completed"
            else:
                last_run = "Running"
            rows.append({
                "id": doc.id,
                "workflow_id": DocumentWorkflows.workflow_id(doc),
                "name": doc.source_label,
                "source_type": doc.get_source_type_display(),
                "status": doc.status,
                "startable": doc.is_unprocessed,
                "last_run": last_run,
                "run_id": doc.workflow_run_id,
                "enqueue_url": reverse("enqueue_document", args=[doc.id]),
                "cancel_url": reverse("cancel_document", args=[doc.id]),
                "progress_url": DocumentProgress.socket_path(doc.id),
            })
        return {
            "kind": "document_runs",
            "title": title,
            "fetched_at": timezone.now().isoformat(),
            "truncated": truncated,
            "documents": rows,
        }

    @tool(response_format="content_and_artifact")
    def list_unfinished_documents(config: RunnableConfig) -> tuple[str, dict]:
        """Show the user every document that is not finished: documents running in Temporal right now (with a Cancel button and live progress) and documents waiting to be processed, i.e. pending or failed (with a Start button). Use this whenever the user asks about pending, unprocessed, failed, processing, running, queued or in-progress documents, or what still needs processing."""
        vendor = config["configurable"]["vendor"]
        active = Document.objects.filter(vendor=vendor, is_active=True).order_by("-created_at")
        running = list(active.filter(status__in=DocumentTools.RUNNING_STATUSES).exclude(workflow_run_id="")[:DocumentTools.MAX_ROWS + 1])
        waiting = list(active.filter(status__in=Document.UNPROCESSED_STATUSES)[:DocumentTools.MAX_ROWS + 1])
        docs = running + waiting
        if not docs:
            return "There are no unfinished documents: nothing is running and nothing is waiting to be processed.", None
        truncated = len(docs) > DocumentTools.MAX_ROWS
        docs = docs[:DocumentTools.MAX_ROWS]
        running = ", ".join(f"{doc.id} ({doc.status})" for doc in docs if doc.status in DocumentTools.RUNNING_STATUSES) or "none"
        pending = ", ".join(str(doc.id) for doc in docs if doc.status == "pending") or "none"
        failed = ", ".join(str(doc.id) for doc in docs if doc.status == "error") or "none"
        more = f" (only the first {DocumentTools.MAX_ROWS} are listed, running ones first)" if truncated else ""
        content = (f"Found {len(docs)} unfinished documents{more}. Document IDs by state: "
                   f"running now: {running}; pending (never processed or canceled): {pending}; failed: {failed}. "
                   "This is the current state: when you mention a document, use only these IDs, never IDs from earlier messages. "
                   "They are shown to the user as a list: running rows have a Cancel button and live progress, the others a Start button. "
                   "Do not repeat the list; summarise it in one sentence.")
        return content, DocumentTools.card("Unfinished documents", docs, truncated)

    @tool(response_format="content_and_artifact")
    def start_document_processing(document_id: str, config: RunnableConfig) -> tuple[str, dict]:
        """Start processing ONE document that the user has explicitly named by its document ID (like 68) or workflow ID (like document-68). Never call this for documents the user did not name, and never to process several or all documents at once; for that, show the pending list instead."""
        vendor = config["configurable"]["vendor"]
        match = re.fullmatch(r"\s*#?(?:document-)?(\d+)\s*", document_id, re.IGNORECASE)
        if match is None:
            return f"'{document_id}' is not a document ID. Use a number like 68 or a workflow ID like document-68.", None
        doc_id = int(match.group(1))
        doc = Document.objects.filter(id=doc_id, vendor=vendor, is_active=True).first()
        if doc is None:
            return f"There is no document {doc_id} in this knowledge base.", None
        if not doc.is_unprocessed:
            return f"Document {doc_id} is {doc.status}; only pending or failed documents can be started.", None
        try:
            chat = config["configurable"].get("chat")
            workflow_id = DocumentWorkflows.start(doc, user=chat.user if chat else None)
        except WorkflowAlreadyStartedError:
            return f"Document {doc_id} is already being processed.", None
        except Exception as error:
            return f"Error: could not start document {doc_id}: {error}", None
        doc.refresh_from_db()
        content = (f"Started processing document {doc_id} as Temporal workflow {workflow_id}. "
                   "Its live progress is shown to the user.")
        return content, DocumentTools.card("Processing started", [doc])


TOOL_REGISTRY = {
    "web_search": web_search,
    "search_documents": search_documents,
    "current_datetime": current_datetime,
    "list_documents": list_documents,
    "calculator": calculator,
    "summarize_chat": summarize_chat,
    "list_datasets": DatasetTools.list_datasets,
    "describe_dataset": DatasetTools.describe_dataset,
    "query_dataset": DatasetTools.query_dataset,
    "make_chart": DatasetTools.make_chart,
    "list_unfinished_documents": DocumentTools.list_unfinished_documents,
    "start_document_processing": DocumentTools.start_document_processing,
}

