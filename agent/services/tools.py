import re
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from temporalio.exceptions import WorkflowAlreadyStartedError
from pgvector.django import L2Distance
from scraper.services.client import OllamaClient
from scraper.models import Chunk, Document
from scraper.services.progress import DocumentProgress
from base.services.temporal import RunningJobs
from scraper.temporal_workflow.temporal import DocumentWorkflows
from chat.models import Message
from chat.services.chat import ChatService
from chat.services.files import ChatFileService
from chat.temporal_workflow.temporal import ChatFileSummaries
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
    NO_DATASET = ("No CSV or Excel file has been uploaded in this chat yet. "
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
        """List every CSV or Excel table uploaded in this chat with its column names. Call this first for any question about data, then pick the table that fits the question, or JOIN tables when the question needs more than one."""
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
        """Run one DuckDB SQL SELECT query over this chat's CSV and Excel tables (you can JOIN them) and return the result rows. Use this for every number you report, and to check a column's real values with SELECT DISTINCT ... LIMIT 10 before filtering on them."""
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

    @tool(response_format="content_and_artifact")
    def make_chart_from_values(title: str, chart_type: str, value_label: str, labels: list[str], values: list[float]) -> tuple[str, dict]:
        """Draw a chart from numbers you found in text, such as a PDF, text file or link read with read_chat_file, or document search results. labels[i] is the name of the bar, point or slice and values[i] its number; both lists must have the same length. value_label says what the numbers are, e.g. "Sales (USD)". chart_type is bar, line or pie. Use it ONLY when the text states the numbers. Never estimate, count or invent values. If the text has no numbers to chart, do not call this; tell the user no chart can be made. For CSV or Excel tables use make_chart instead."""
        if chart_type not in DatasetTools.CHART_TYPES:
            return f"Error: chart_type must be one of {', '.join(DatasetTools.CHART_TYPES)}.", None
        if not labels or len(labels) != len(values):
            return f"Error: labels and values must be non-empty lists of the same length (got {len(labels)} and {len(values)}).", None
        if len(labels) > DatasetService.MAX_ROWS:
            return f"Error: at most {DatasetService.MAX_ROWS} points can be charted.", None
        chart = {
            "kind": "chart",
            "type": chart_type,
            "title": title,
            "label": value_label,
            "labels": [str(label) for label in labels],
            "values": values,
        }
        points = "\n".join(f"{label} | {value}" for label, value in zip(labels, values))
        return ("The chart is shown to the user. It contains these values; tell the user they were taken from the text "
                "and should be checked against it:\n" + points), chart


class DocumentTools:
    MAX_ROWS = 50

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

    @staticmethod
    def chat_documents(config):
        chat = config["configurable"].get("chat")
        if chat is None:
            return Document.objects.none()
        vendor = config["configurable"]["vendor"]
        shown = DocumentTools.card_document_ids(chat)
        return (Document.objects.filter(Q(chat_messages__chat=chat) | Q(id__in=shown), vendor=vendor, is_active=True)
                .distinct().order_by("-id"))

    @staticmethod
    def card_document_ids(chat):
        messages = chat.messages.visible().filter(role="assistant", message__contains=Message.ARTIFACT_MARKER)
        cards = [m.artifact for m in messages if m.artifact and m.artifact.get("kind") == "document_runs"]
        return {row["id"] for card in cards for row in card.get("documents", []) if "id" in row}

    @staticmethod
    def vendor_documents(config):
        return Document.objects.filter(vendor=config["configurable"]["vendor"], is_active=True).order_by("-id")

    @tool
    def list_chat_workflows(config: RunnableConfig) -> str:
        """List the Temporal workflow IDs and current status of this chat's documents: chat files and links added to the knowledge base, and documents shown in a document card earlier in this chat. Includes completed ones. This is the default for any question about workflows or workflow IDs. Only when the user asks to see the pending or unfinished documents themselves, use list_unfinished_documents instead."""
        docs = list(DocumentTools.chat_documents(config)[:DocumentTools.MAX_ROWS])
        if not docs:
            return "This chat has no documents yet: no chat file was added to the knowledge base and no document card was shown, so there are no workflow IDs to list."
        lines = [
            f"- {DocumentWorkflows.workflow_id(doc)}: {doc.source_label} ({doc.status}{'' if doc.workflow_run_id else ', never run'})"
            for doc in docs
        ]
        return "Workflow IDs of this chat's documents, newest first, with their current status:\n" + "\n".join(lines)

    JOB_CLASSES = (DocumentWorkflows, ChatFileSummaries)

    @staticmethod
    def job_card(title, executions):
        rows = []
        for execution in executions:
            job = RunningJobs.owner(execution, DocumentTools.JOB_CLASSES)
            rows.append({
                "workflow_id": execution.id,
                "name": job.job_label(execution.id),
                "readonly": True,
                "status": "running",
                "run_id": execution.run_id,
                "started_at": execution.start_time.isoformat(),
                "progress_url": job.job_socket_path(execution.id, execution.run_id),
            })
        return {
            "kind": "document_runs",
            "title": title,
            "fetched_at": timezone.now().isoformat(),
            "truncated": False,
            "documents": rows,
        }

    @tool(response_format="content_and_artifact")
    def list_running_jobs() -> tuple[str, dict]:
        """Show the jobs running in Temporal right now, read from Temporal itself, with live progress: document processing jobs and chat file summary jobs. Use this when the user asks for pending tasks or jobs, or what is being processed at the moment. For documents that are not processed yet, use list_unfinished_documents instead."""
        try:
            executions = RunningJobs.fetch(DocumentTools.JOB_CLASSES)
        except Exception as error:
            return f"Error: could not read the running jobs from Temporal: {error}", None
        if not executions:
            return "No jobs are running in Temporal right now.", None
        jobs = ", ".join(
            f"{execution.id} ({RunningJobs.owner(execution, DocumentTools.JOB_CLASSES).job_label(execution.id)})"
            for execution in executions
        )
        content = (f"{len(executions)} jobs are running in Temporal right now: {jobs}. "
                   "They are shown to the user as a list with live progress. "
                   "Do not repeat the list; summarise it in one sentence.")
        return content, DocumentTools.job_card("Running jobs", executions)

    @tool(response_format="content_and_artifact")
    def list_unfinished_documents(config: RunnableConfig) -> tuple[str, dict]:
        """Show the user all documents of the knowledge base that are not processed yet, not only this chat's: pending (never processed or canceled) or failed, each with a Start button. Use this ONLY when the user asks to see pending, unprocessed or failed documents. For jobs running right now, use list_running_jobs. For questions about workflow IDs, use list_chat_workflows instead."""
        active = DocumentTools.vendor_documents(config)
        docs = list(active.filter(status__in=Document.UNPROCESSED_STATUSES)[:DocumentTools.MAX_ROWS + 1])
        if not docs:
            return "There are no unprocessed documents: nothing is pending or failed.", None
        truncated = len(docs) > DocumentTools.MAX_ROWS
        docs = docs[:DocumentTools.MAX_ROWS]
        pending = ", ".join(str(doc.id) for doc in docs if doc.status == "pending") or "none"
        failed = ", ".join(str(doc.id) for doc in docs if doc.status == "error") or "none"
        more = f" (only the newest {DocumentTools.MAX_ROWS} are listed)" if truncated else ""
        content = (f"Found {len(docs)} unprocessed documents in the knowledge base{more}. Document IDs by state: "
                   f"pending (never processed or canceled): {pending}; failed: {failed}. "
                   "This is the current state: when you mention a document, use only these IDs, never IDs from earlier messages. "
                   "They are shown to the user as a list, each with a Start button. "
                   "Do not repeat the list; summarise it in one sentence.")
        return content, DocumentTools.card("Unprocessed documents", docs, truncated)

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


class ChatFileTools:
    NO_FILES = ("No file or link has been added to this chat yet. "
                "Ask the user to upload one with the Upload file button or add one with Add link.")

    @staticmethod
    def chat(config):
        return config["configurable"].get("chat")

    @staticmethod
    def describe(message):
        kind = "link" if message.url else message.extension.lstrip(".")
        line = f"- file id {message.id}: {message.file_label} ({kind})"
        if message.is_dataset:
            line += ", a table: use the dataset tools for it"
        if message.document_id:
            doc = message.document
            line += f", in the knowledge base as {DocumentWorkflows.workflow_id(doc)} ({doc.status})"
        return line

    @staticmethod
    def missing(file_id):
        return f"There is no file with id {file_id} in this chat. Call list_chat_files to see this chat's files."

    @tool
    def list_chat_files(config: RunnableConfig) -> str:
        """List every file and link the user added to this chat, with its file id, including ones from older messages you can no longer see. Call this when the user refers to a file you cannot find in the conversation, or asks which files this chat has."""
        files = ChatFileService.for_chat(ChatFileTools.chat(config))
        if not files:
            return ChatFileTools.NO_FILES
        return "Files in this chat:\n" + "\n".join(ChatFileTools.describe(message) for message in files)

    @tool
    def read_chat_file(file_id: int, config: RunnableConfig) -> str:
        """Read the text of a PDF, text file or link the user added to this chat, to answer a question about it. Pick the file from the conversation by its name: each one is shown as [attached file: name, file id N]. If you cannot tell which file the user means, call list_chat_files or ask the user. CSV and Excel files are tables: use the dataset tools for those. Use this also when the user asks to summarise a file; only when they ask to process it, use process_chat_file."""
        message = ChatFileService.find(ChatFileTools.chat(config), file_id)
        if message is None:
            return ChatFileTools.missing(file_id)
        if message.is_dataset:
            return f"{message.file_label} is a table. Use list_datasets and query_dataset for it."
        try:
            text = ChatFileService.read_text(message)
        except Exception as error:
            return f"Error: could not read {message.file_label}: {error}"
        if not text.strip():
            return f"{message.file_label} has no readable text. A scanned PDF holds only images."
        limit = ChatFileService.MAX_CHARS
        if len(text) > limit:
            text = text[:limit] + f"\n\n(text cut: only the first {limit} of {len(text)} characters are shown)"
        return f"Text of {message.file_label}:\n\n{text}"

    @tool(response_format="content_and_artifact")
    def add_to_knowledge_base(file_id: int, config: RunnableConfig) -> tuple[str, dict]:
        """Add a PDF, text file or link from this chat to the central knowledge base and start processing it in Temporal. Call this ONLY when the user explicitly asks to add a file to the knowledge base or central context. Never call it just because a file was uploaded or a question was asked about it."""
        chat = ChatFileTools.chat(config)
        message = ChatFileService.find(chat, file_id)
        if message is None:
            return ChatFileTools.missing(file_id), None
        if message.is_dataset:
            return f"{message.file_label} is a table. CSV and Excel files stay in the chat and cannot be added to the knowledge base.", None
        try:
            doc, created = ChatFileService.add_to_knowledge_base(message, config["configurable"]["vendor"], chat.user)
        except Exception as error:
            return f"Error: could not add {message.file_label} to the knowledge base: {error}", None
        workflow_id = DocumentWorkflows.workflow_id(doc)
        if not created:
            content = (f"{message.file_label} is already in the knowledge base as document {doc.id} "
                       f"(workflow {workflow_id}, status {doc.status}). Nothing new was added.")
            return content, DocumentTools.card("Already in the knowledge base", [doc])
        try:
            ChatFileService.start_processing(doc, chat.user)
        except Exception as error:
            content = (f"Added {message.file_label} to the knowledge base as document {doc.id} ({workflow_id}), "
                       f"but processing could not start: {error}. It can be started later.")
            return content, DocumentTools.card("Added to the knowledge base", [doc])
        content = (f"Added {message.file_label} to the knowledge base as document {doc.id} and started processing it "
                   f"as Temporal workflow {workflow_id}. Its live progress is shown to the user.")
        return content, DocumentTools.card("Added to the knowledge base", [doc])


    @tool(response_format="content_and_artifact")
    def process_chat_file(file_id: int, config: RunnableConfig) -> tuple[str, dict]:
        """Process a PDF, text file or link from this chat: a Temporal workflow summarises it piece by piece, saves the summary and posts it in the chat as a new message when it is done. Call this ONLY when the user asks to PROCESS a file they name. Pick the file by its name: each one is shown as [attached file: name, file id N]. If the user asks to summarise a file, use read_chat_file and summarise it yourself instead. If the user mentions the knowledge base or central context, use add_to_knowledge_base instead."""
        chat = ChatFileTools.chat(config)
        message = ChatFileService.find(chat, file_id)
        if message is None:
            return ChatFileTools.missing(file_id), None
        if message.is_dataset:
            return f"{message.file_label} is a table. Use list_datasets and query_dataset for it.", None
        workflow_id = ChatFileSummaries.workflow_id(message)
        try:
            run_id = ChatFileSummaries.start(message)
        except WorkflowAlreadyStartedError:
            return f"{message.file_label} is already being processed as Temporal workflow {workflow_id}.", None
        except Exception as error:
            return f"Error: could not start processing {message.file_label}: {error}", None
        content = (f"Started processing {message.file_label} as Temporal workflow {workflow_id}. "
                   "A card shows its live progress and the summary will be posted in this chat when it is done. "
                   "Tell the user this in one sentence; do not summarise the file yourself.")
        card = {
            "kind": "file_summary",
            "title": f"Processing {message.file_label}",
            "file_id": message.id,
            "name": message.file_label,
            "workflow_id": workflow_id,
            "run_id": run_id,
            "progress_url": ChatFileSummaries.socket_path(message, run_id),
        }
        return content, card


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
    "make_chart_from_values": DatasetTools.make_chart_from_values,
    "list_unfinished_documents": DocumentTools.list_unfinished_documents,
    "list_running_jobs": DocumentTools.list_running_jobs,
    "start_document_processing": DocumentTools.start_document_processing,
    "list_chat_workflows": DocumentTools.list_chat_workflows,
    "list_chat_files": ChatFileTools.list_chat_files,
    "read_chat_file": ChatFileTools.read_chat_file,
    "add_to_knowledge_base": ChatFileTools.add_to_knowledge_base,
    "process_chat_file": ChatFileTools.process_chat_file,
}

