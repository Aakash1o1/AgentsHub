from django.core.management.base import BaseCommand
from scraper.models import Document
from scraper.services.ingestion import ScraperService



class Command(BaseCommand):
    help = "Background worker: embeds pending documents one at a time"

    def handle(self, * args, **options):
        pending = Document.objects.filter(status="pending").order_by("created_at")
        self.stdout.write(f"Found {pending.count()} pending docs")

        service = ScraperService()
        for doc in pending:
            self.stdout.write(f"Processing doc {doc.id}...")
            status, count, error = service.vectorize(doc.as_message())
            self.stdout.write(f"Done doc {doc.id}: {status}, {count} chunks {error}")

        self.stdout.write("All pending docs processed. Stopping.")
