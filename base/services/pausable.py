from temporalio import workflow


class PausableWorkflow:
    PAUSE = "pause"
    RESUME = "resume"
    SIGNALS = {PAUSE: True, RESUME: False}

    def __init__(self):
        self.paused = False

    @workflow.signal(name=PAUSE)
    def pause(self):
        self.paused = True
        self.pause_changed()

    @workflow.signal(name=RESUME)
    def resume(self):
        self.paused = False
        self.pause_changed()

    def pause_changed(self):
        return None

    async def wait_while_paused(self):
        await workflow.wait_condition(lambda: not self.paused)
