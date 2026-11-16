import io, requests
from pypdf import PdfReader
from bs4 import BeautifulSoup
from scraper.services.client import OllamaClient
from django.core.files.storage import default_storage
from django.utils import timezone
from scraper.models import Chunk, Document
from chat.services.notifier import ChatNotifier


class ScraperService:
    CHUNK_SIZE = 512
    CHUNK_OVERLAP = 100

    def __init__(self):
        self.ollama = OllamaClient()

    # Make chunks
    def chunk_text(self, text):
        chunks = []
        start = 0
        while start < len(text):
            end = start + ScraperService.CHUNK_SIZE
            chunks.append(text[start:end])
            start = end - ScraperService.CHUNK_OVERLAP
        return chunks
    
    @staticmethod
    def extract_pdf(stream):
        reader = PdfReader(stream)
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    @staticmethod
    def fetch_pdf(url, timeout):
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return ScraperService.extract_pdf(io.BytesIO(response.content))

    @staticmethod
    def read_stored_file(file_name, source_type):
        with default_storage.open(file_name, "rb") as fh:
            if source_type == "pdf":
                return ScraperService.extract_pdf(io.BytesIO(fh.read()))
            return fh.read().decode("utf-8", errors="replace")

    @staticmethod
    def fetch_website(url, timeout):
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)
    
    




    @staticmethod
    def fetch_data(url,timeout):
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        if "charset" not in response.headers.get("Content-Type", ""):
            response.encoding = "utf-8"
        return response.text

    @staticmethod
    def read_source(message):
        source_type = message["source_type"]
        if message["file_name"]:
            return ScraperService.read_stored_file(message["file_name"], source_type)
        if source_type == "pdf":
            return ScraperService.fetch_pdf(message["url"], 180)
        if source_type == "website":
            return ScraperService.fetch_website(message["url"], 180)
        return ScraperService.fetch_data(message["url"], 180)




    def vectorize(self, message):
        doc_id = message["document_id"]
        if self.claim(doc_id) == 0:
            return "skipped", 0, ""

        Chunk.objects.filter(parent_doc_id=doc_id).delete()

        try:
            pieces = self.chunk_text(self.read_source(message))
            Chunk.objects.bulk_create([
                Chunk(
                    parent_doc_id=doc_id,
                    chunk_num=i,
                    content=piece,
                    embedding=self.ollama.embed(piece),
                )
                for i, piece in enumerate(pieces)
            ])
            self.finish(doc_id, "completed")
            self.announce(message, "completed")
            return "completed", len(pieces), ""
        except Exception as e:
            reason = f"{type(e).__name__}: {e}"
            self.finish(doc_id, "error", reason)
            self.announce(message, "error", reason)
            return "error", 0, reason

    @staticmethod
    def announce(message, status, error=""):
        try:
            ChatNotifier.document_finished(
                message.get("vendor_id"), message.get("document_id"), status, error
            )
        except Exception:
            pass



    @staticmethod
    def claim(doc_id):
        return Document.objects.filter(id=doc_id, is_active=True).exclude(status="completed").update(
            status="processing", error="", updated_at=timezone.now()
        )

    @staticmethod
    def finish(doc_id, status, error=""):
        Document.objects.filter(id=doc_id).update(
            status=status, error=error, updated_at=timezone.now()
        )
