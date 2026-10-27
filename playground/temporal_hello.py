import asyncio
import sys
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker


class Greeter:
    @activity.defn
    async def slow_greet(self, name: str) -> str:
        print(f"activity running for {name}")
        await asyncio.sleep(5)
        return f"Hello {name}"


@workflow.defn
class HelloWorkflow:
    @workflow.run
    async def run(self) -> list:
        print("workflow code running")
        greetings = []
        for name in ["a", "b", "c"]:
            greeting = await workflow.execute_activity_method(
                Greeter.slow_greet,
                name,
                start_to_close_timeout=timedelta(seconds=10),
            )
            greetings.append(greeting)
        return greetings


class HelloApp:
    ADDRESS = "localhost:7233"
    TASK_QUEUE = "hello"
    WORKFLOW_ID = "hello-workflow"

    async def worker(self):
        client = await Client.connect(self.ADDRESS)
        print(f"worker polling task queue '{self.TASK_QUEUE}'")
        await Worker(
            client,
            task_queue=self.TASK_QUEUE,
            workflows=[HelloWorkflow],
            activities=[Greeter().slow_greet],
        ).run()

    async def start(self):
        client = await Client.connect(self.ADDRESS)
        result = await client.execute_workflow(
            HelloWorkflow.run,
            id=self.WORKFLOW_ID,
            task_queue=self.TASK_QUEUE,
        )
        print(f"workflow result: {result}")

    def run(self, argv):
        commands = {"worker": self.worker, "start": self.start}
        if len(argv) != 2 or argv[1] not in commands:
            print("usage: python playground/temporal_hello.py worker|start")
            return
        asyncio.run(commands[argv[1]]())


if __name__ == "__main__":
    HelloApp().run(sys.argv)
