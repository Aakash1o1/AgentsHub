import re
from typing import Literal
from django.urls import reverse
from django.utils import timezone
from temporalio.exceptions import WorkflowAlreadyStartedError
from pgvector.django import L2Distance
from scraper.services.client import OllamaClient
from scraper.models import Chunk, Document
from scraper.services.progress import DocumentProgress
from scraper.temporal_workflow.temporal import DocumentWorkflows
from base.services.temporal import TemporalClient, WorkflowRun
from chat.services.access import TaskAccess
from chat.services.chat import ChatService
from chat.services.files import ChatFileService
from chat.services.jobs import ChatJobs
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


class TaskGate:
    REPLY = TaskAccess.DENIED + " Tell the user exactly this, and that an admin can give them the permission."

    @staticmethod
    def denied(config):
        chat = config["configurable"].get("chat")
        return not TaskAccess.allowed(chat.user if chat else None)


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
        return (Document.objects.filter(chat_messages__chat=chat, vendor=config["configurable"]["vendor"], is_active=True)
                .distinct().order_by("-id"))

    @staticmethod
    def vendor_documents(config):
        return Document.objects.filter(vendor=config["configurable"]["vendor"], is_active=True).order_by("-id")

    @tool
    def list_chat_workflows(config: RunnableConfig) -> str:
        """List the Temporal workflow IDs of this chat's files that were added to the knowledge base, with the status of their newest run read from Temporal. Use this only when the user asks for workflow IDs. For tasks, use show_tasks instead."""
        if TaskGate.denied(config):
            return TaskGate.REPLY
        docs = list(DocumentTools.chat_documents(config)[:DocumentTools.MAX_ROWS])
        if not docs:
            return "No file of this chat was added to the knowledge base, so there are no workflow IDs to list."
        try:
            runs = ChatJobs.runs_of([DocumentWorkflows.workflow_id(doc) for doc in docs], config["configurable"]["vendor"].id)
        except Exception as error:
            return f"Error: could not read the workflows from Temporal: {error}"
        lines = []
        for doc in docs:
            workflow_id = DocumentWorkflows.workflow_id(doc)
            run = runs.get(workflow_id)
            lines.append(f"- {workflow_id}: {doc.source_label} ({run.status_name if run else 'never run'})")
        return "Workflow IDs of this chat's files in the knowledge base, newest first, with their Temporal status:\n" + "\n".join(lines)

    @tool(response_format="content_and_artifact")
    def show_tasks(tab: Literal["running", "failed", "todo", "done"], config: RunnableConfig) -> tuple[str, dict]:
        """Show the user's tasks from all their chats (file summaries and knowledge-base processing) in one card read from Temporal, with the tabs Running, Failed, To do and Done. Running, Failed and Done cover all chats; To do lists only this chat's files whose tasks never started. tab picks the tab that opens first:
- "done" for recent, recently done, latest, finished or completed tasks, including "all recent tasks" or "what finished".
- "running" only when the user asks what is running, paused or being processed right now.
- "failed" for failed, cancelled or stopped tasks.
- "todo" for pending, unfinished, left or not started tasks.
Use this whenever the user asks about tasks or jobs."""
        if TaskGate.denied(config):
            return TaskGate.REPLY, None
        chat = config["configurable"].get("chat")
        if chat is None:
            return "There is no chat, so there are no tasks to list.", None
        try:
            rows = ChatJobs.tasks(chat.user, chat)
        except Exception as error:
            return f"Error: could not read the tasks from Temporal: {error}", None
        if not rows:
            return "There are no tasks: nothing ran in your chats and this chat has no files to start.", None
        content = ("The tasks are shown to the user as a card. Reply with exactly this sentence and nothing else: "
                   "Here are the tasks.")
        card = {"kind": "chat_tasks", "tab": tab if tab in ChatJobs.TABS else "running", "chat_id": chat.id,
                "fetched_at": timezone.now().isoformat(), "tasks": rows}
        return content, card

    @tool(response_format="content_and_artifact")
    def start_document_processing(document_ids: list[str], config: RunnableConfig) -> tuple[str, dict]:
        """Start the knowledge-base job (chunking and embedding) of documents that are already in the knowledge base, named by the user by their document IDs (like 68) or workflow IDs (like document-68). Pass every ID the user names, at most 5 are started per request. Never call this for documents the user did not name, and never when the user asks to process a chat file: that is process_chat_file."""
        vendor = config["configurable"]["vendor"]
        chat = config["configurable"].get("chat")
        lines, started = [], []
        for document_id in document_ids:
            match = re.fullmatch(r"\s*#?(?:document-)?(\d+)\s*", str(document_id), re.IGNORECASE)
            if match is None:
                lines.append(f"- '{document_id}': not a document ID (use a number like 68 or document-68)")
                continue
            doc_id = int(match.group(1))
            doc = Document.objects.filter(id=doc_id, vendor=vendor, is_active=True).first()
            if doc is None:
                lines.append(f"- document {doc_id}: not in this knowledge base")
            elif not doc.is_unprocessed:
                lines.append(f"- document {doc_id}: skipped, it is {doc.status}; only pending or failed documents can be started")
            elif len(started) >= ChatFileTools.MAX_FILES:
                lines.append(f"- document {doc_id}: not started, the limit is {ChatFileTools.MAX_FILES} per request")
            else:
                try:
                    workflow_id = DocumentWorkflows.start(doc, user=chat.user if chat else None)
                except WorkflowAlreadyStartedError:
                    lines.append(f"- document {doc_id}: skipped, it is already being processed")
                    continue
                except Exception as error:
                    lines.append(f"- document {doc_id}: could not start: {error}")
                    continue
                doc.refresh_from_db()
                started.append(doc)
                lines.append(f"- document {doc_id}: started as Temporal workflow {workflow_id}")
        content = ChatFileTools.report("Knowledge-base jobs", lines, started)
        return content, DocumentTools.card("Processing started", started) if started else None


class ChatFileTools:
    JOBS = {"summary": "summary", "knowledge_base": "knowledge-base"}
    CONTROLS = {"pause": "Paused", "resume": "Resumed", "cancel": "Canceled"}
    MAX_FILES = 5
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

    @staticmethod
    def pick(chat, file_ids, all_files):
        files = ChatFileService.for_chat(chat)
        if all_files:
            return [message for message in files if not message.is_dataset], []
        by_id = {message.id: message for message in files}
        chosen, lines = [], []
        for file_id in dict.fromkeys(file_ids or []):
            message = by_id.get(file_id)
            if message is None:
                lines.append(f"- file id {file_id}: not in this chat")
            elif message.is_dataset:
                lines.append(f"- {message.file_label}: skipped, it is a table (use the dataset tools)")
            else:
                chosen.append(message)
        return chosen, lines

    @staticmethod
    def report(title, lines, started):
        if not lines:
            return "No file was named and none fits. Ask the user which files they mean, or call list_chat_files."
        body = f"{title}, one line per file:\n" + "\n".join(lines)
        if started:
            body += "\nA tasks card with live progress is shown to the user."
        return body + "\nTell the user briefly which ones started and which were skipped and why. Do not summarise the files yourself."

    @staticmethod
    def tasks_card(chat, running_keys):
        try:
            rows = ChatJobs.tasks(chat.user)
        except Exception:
            return None
        for row in rows:
            if row["key"] in running_keys:
                row.update(tab="running", reason="", finished_at=None, **running_keys[row["key"]])
        return {"kind": "chat_tasks", "tab": "running", "fetched_at": timezone.now().isoformat(), "tasks": rows}

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
    def add_to_knowledge_base(config: RunnableConfig, file_ids: list[int] | None = None, all_files: bool = False) -> tuple[str, dict]:
        """Add PDFs, text files or links from this chat to the central knowledge base and start their knowledge-base job (chunking and embedding) in Temporal. Pass the file id of every file the user names in file_ids; each file is shown as [attached file: name, file id N]. Set all_files to true when the user asks to add all files. At most 5 files are added per request; files already in the knowledge base are skipped. Call this ONLY when the user explicitly asks to add files to the knowledge base or central context. Never call it just because a file was uploaded or a question was asked about it."""
        chat = ChatFileTools.chat(config)
        chosen, lines = ChatFileTools.pick(chat, file_ids, all_files)
        started = {}
        for message in chosen:
            if message.document_id:
                doc = message.document
                lines.append(f"- {message.file_label}: skipped, already in the knowledge base as document {doc.id} ({doc.status})")
                continue
            if len(started) >= ChatFileTools.MAX_FILES:
                lines.append(f"- {message.file_label}: not added, the limit is {ChatFileTools.MAX_FILES} files per request")
                continue
            try:
                doc, _ = ChatFileService.add_to_knowledge_base(message, config["configurable"]["vendor"], chat.user)
            except Exception as error:
                lines.append(f"- {message.file_label}: could not add it: {error}")
                continue
            try:
                workflow_id = ChatFileService.start_processing(doc, chat.user)
            except Exception as error:
                lines.append(f"- {message.file_label}: added as document {doc.id}, but processing could not start: {error}")
                continue
            started[f"kb-{message.id}"] = {}
            lines.append(f"- {message.file_label}: added as document {doc.id} and processing started ({workflow_id})")
        content = ChatFileTools.report("Adding to the knowledge base", lines, started)
        return content, ChatFileTools.tasks_card(chat, started) if started else None

    @tool(response_format="content_and_artifact")
    def process_chat_file(config: RunnableConfig, file_ids: list[int] | None = None, all_files: bool = False) -> tuple[str, dict]:
        """Process PDFs, text files or links from this chat: for each one a Temporal workflow summarises it piece by piece and posts the summary in the chat as a new message when it is done. Call this whenever the user asks to PROCESS files of this chat. Pass the file id of every file the user names in file_ids; each file is shown as [attached file: name, file id N]. Set all_files to true when the user asks to process all files. At most 5 files are started per request; files already processed or being processed are skipped. Processing never adds files to the knowledge base. If the user asks to summarise a file, use read_chat_file and summarise it yourself instead. If the user mentions the knowledge base or central context, use add_to_knowledge_base instead."""
        chat = ChatFileTools.chat(config)
        chosen, lines = ChatFileTools.pick(chat, file_ids, all_files)
        try:
            runs = ChatJobs.runs_of([ChatFileSummaries.workflow_id(message) for message in chosen], chat.vendor_id)
        except Exception as error:
            return f"Error: could not read the tasks from Temporal: {error}", None
        started = {}
        for message in chosen:
            run = runs.get(ChatFileSummaries.workflow_id(message))
            if run is not None and run.status in WorkflowRun.ACTIVE:
                lines.append(f"- {message.file_label}: skipped, it is being processed already")
                continue
            if run is not None and run.status == WorkflowRun.COMPLETED:
                lines.append(f"- {message.file_label}: skipped, it was processed already")
                continue
            if len(started) >= ChatFileTools.MAX_FILES:
                lines.append(f"- {message.file_label}: not started, the limit is {ChatFileTools.MAX_FILES} files per request")
                continue
            try:
                run_id = ChatFileSummaries.start(message)
            except WorkflowAlreadyStartedError:
                lines.append(f"- {message.file_label}: skipped, it is processed or being processed already")
                continue
            except Exception as error:
                lines.append(f"- {message.file_label}: could not start: {error}")
                continue
            started[f"summary-{message.id}"] = {"progress_url": ChatFileSummaries.socket_path(message, run_id)}
            lines.append(f"- {message.file_label}: started ({ChatFileSummaries.workflow_id(message)})")
        content = ChatFileTools.report("Processing", lines, started)
        return content, ChatFileTools.tasks_card(chat, started) if started else None


class TaskControlTools:
    @staticmethod
    def workflow_id(message, job):
        if job == "summary":
            return ChatFileSummaries.workflow_id(message)
        return DocumentWorkflows.workflow_id(message.document) if message.document_id else None

    @tool(response_format="content_and_artifact")
    def control_task(job: str, action: str, config: RunnableConfig, file_ids: list[int] | None = None,
                     all_files: bool = False) -> tuple[str, dict]:
        """Pause, resume or cancel running tasks of files in this chat, the same as the Pause, Resume and Cancel buttons. job is "summary" (the files' summary tasks) or "knowledge_base" (adding the files to the knowledge base). action is "pause", "resume" or "cancel". Pass the file id of every file the user names in file_ids, or set all_files to true when the user says all. Use this only when the user asks to pause, resume, continue, stop or cancel tasks. If you do not know the file ids, call list_chat_files first."""
        if TaskGate.denied(config):
            return TaskGate.REPLY, None
        if job not in ChatFileTools.JOBS:
            return 'Error: job must be "summary" or "knowledge_base".', None
        if action not in ChatFileTools.CONTROLS:
            return 'Error: action must be "pause", "resume" or "cancel".', None
        chat = ChatFileTools.chat(config)
        chosen, lines = ChatFileTools.pick(chat, file_ids, all_files)
        targets = {message: TaskControlTools.workflow_id(message, job) for message in chosen}
        try:
            runs = ChatJobs.runs_of([workflow_id for workflow_id in targets.values() if workflow_id], chat.vendor_id)
        except Exception as error:
            return f"Error: could not read the tasks from Temporal: {error}", None
        done = 0
        for message, workflow_id in targets.items():
            name = f"{ChatFileTools.JOBS[job]} task of {message.file_label}"
            run = runs.get(workflow_id) if workflow_id else None
            if all_files and (run is None or run.status not in WorkflowRun.ACTIVE):
                continue
            if workflow_id is None:
                lines.append(f"- {message.file_label}: never added to the knowledge base, so it has no knowledge-base task")
            elif run is None or run.status not in WorkflowRun.ACTIVE:
                lines.append(f"- {name}: not running, nothing to {action}")
            elif action == "resume" and run.status != WorkflowRun.PAUSED:
                lines.append(f"- {name}: not paused, nothing to resume")
            elif action == "pause" and run.status == WorkflowRun.PAUSED:
                lines.append(f"- {name}: already paused")
            else:
                try:
                    getattr(TemporalClient, action)(workflow_id, run.run_id, f"{ChatFileTools.CONTROLS[action]} from chat {chat.id}")
                except Exception as error:
                    lines.append(f"- {name}: could not {action}: {error}")
                    continue
                done += 1
                lines.append(f"- {name}: {ChatFileTools.CONTROLS[action].lower()}")
        if not lines and all_files:
            return f"No {ChatFileTools.JOBS[job]} task of this chat is running, so there is nothing to {action}.", None
        if not lines:
            return "No file was named and none fits. Ask the user which files they mean, or call list_chat_files.", None
        content = (f"Result, one line per file:\n" + "\n".join(lines) +
                   "\nTell the user briefly what was done and what was skipped and why.")
        return content, ChatFileTools.tasks_card(chat, {}) if done else None


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
    "show_tasks": DocumentTools.show_tasks,
    "start_document_processing": DocumentTools.start_document_processing,
    "list_chat_workflows": DocumentTools.list_chat_workflows,
    "list_chat_files": ChatFileTools.list_chat_files,
    "read_chat_file": ChatFileTools.read_chat_file,
    "add_to_knowledge_base": ChatFileTools.add_to_knowledge_base,
    "process_chat_file": ChatFileTools.process_chat_file,
    "control_task": TaskControlTools.control_task,
}

