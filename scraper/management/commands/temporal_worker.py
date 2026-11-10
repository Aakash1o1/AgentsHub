import asyncio
from concurrent.futures import ThreadPoolExecutor

from django.core.management.base import BaseCommand
from temporalio.worker import Worker

from base.services.keycloak import KeycloakToken
from chat.temporal_workflow.activities import ChatFileSummaryActivities
from chat.temporal_workflow.workflows import ChatFileSummaryWorkflow
from scraper.temporal_workflow.activities import DocumentActivities
from scraper.temporal_workflow.temporal import DocumentWorkflows
from scraper.temporal_workflow.workflows import DocumentWorkflow


class Command(BaseCommand):
    help = "Temporal worker: runs DocumentWorkflow, ChatFileSummaryWorkflow and their activities"

    ACTIVITY_THREADS = 4

    def handle(self, *args, **options):
        try:
            asyncio.run(self.run_worker())
        except KeyboardInterrupt:
            self.stdout.write("\nStopping.")

    # THis starts performing activities in the threads.
    # 
    async def run_worker(self):
        token = KeycloakToken.for_worker()
        client = await DocumentWorkflows.connect(token)
        refresher = asyncio.create_task(DocumentWorkflows.keep_token_fresh(client, token))
        acts = DocumentActivities()
        summary = ChatFileSummaryActivities()
        try:
            with ThreadPoolExecutor(max_workers=self.ACTIVITY_THREADS) as executor:
                worker = Worker(
                    client, # SErver connection to use
                    task_queue=DocumentWorkflows.TASK_QUEUE, #queue name
                    workflows=[DocumentWorkflow, ChatFileSummaryWorkflow],# Workflow name(class we named as workflow)
                    activities=[acts.mark_stage, acts.extract_text, acts.embed_batch, acts.finish, acts.announce,
                                summary.read_text, summary.summarize_piece, summary.combine,
                                summary.save_summary, summary.post_summary], # Activity names it can handle
                    activity_executor=executor,#
                )
                self.stdout.write(f"Worker polling task queue '{DocumentWorkflows.TASK_QUEUE}'. Ctrl-C to stop.")
                await worker.run()
        finally:
            refresher.cancel()
