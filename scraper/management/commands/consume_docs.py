from django.core.management.base import BaseCommand

from scraper.models import Document
from scraper.services.ingestion import ScraperService
from scraper.services.queue import DocumentQueue


class Command(BaseCommand):
    help = "Kafka consumer: embeds queued documents one at a time, priority first"

    POLL_TIMEOUT_MS = 1000
    



    def handle(self, *args, **options):
        DocumentQueue.ensure_topics()
        consumer = DocumentQueue.consumer()
        normal = DocumentQueue.partition(DocumentQueue.TOPIC_NORMAL)
        service = ScraperService()

        self.stdout.write("Waiting for documents. Ctrl-C to stop.")
        try:
            while True:
                # check priority topic first
                record = self.next_record(consumer, normal)
                if record is None:
                    continue
                self.embed(service, record.value)
                # Update offset
                DocumentQueue.commit(consumer, record)
        except KeyboardInterrupt:
            self.stdout.write("\nStopping.")
        finally:
            consumer.close()

    def next_record(self, consumer, normal):
        # Pause the normal topic and fetch data from all other topics
        consumer.pause(normal)
        batch = consumer.poll(timeout_ms=self.POLL_TIMEOUT_MS, max_records=1)
        consumer.resume(normal)

        if not batch:
            batch = consumer.poll(timeout_ms=self.POLL_TIMEOUT_MS, max_records=1)

        for records in batch.values():
            if records:
                return records[0]
        return None

    def embed(self, service, message):
        doc_id = message.get("document_id")

        if message.get("schema_version") != Document.MESSAGE_SCHEMA_VERSION:
            self.stdout.write(f"doc {doc_id}: unknown message schema, skipping")
            return

        self.stdout.write(f"doc {doc_id}: embedding ({message['source_type']})...")
        status, count, error = service.vectorize(message)
        self.stdout.write(f"doc {doc_id}: {status}, {count} chunks")
        if error:
            self.stdout.write(f"doc {doc_id}: {error}")
