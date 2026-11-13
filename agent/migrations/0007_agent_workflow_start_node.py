from django.db import migrations


class StartNode:
    STEP_GAP = 280

    @staticmethod
    def step_of(workflow):
        nodes = (workflow or {}).get("nodes") or []
        return next((node for node in nodes if node.get("type") == "step"), None)

    @classmethod
    def forward(cls, apps, schema_editor):
        Agent = apps.get_model("agent", "Agent")
        for agent in Agent.objects.all():
            step = cls.step_of(agent.workflow_json)
            if step is None:
                continue
            position = step.get("position") or {"x": 40, "y": 120}
            step["position"] = {"x": position["x"] + cls.STEP_GAP, "y": position["y"]}
            agent.workflow_json = {
                "nodes": [
                    {"id": "start-1", "type": "start", "position": {"x": position["x"], "y": position["y"]}, "data": {}},
                    step,
                ],
                "edges": [{"id": "edge-1", "source": "start-1", "target": step["id"], "data": {}}],
            }
            agent.save(update_fields=["workflow_json"])

    @classmethod
    def backward(cls, apps, schema_editor):
        Agent = apps.get_model("agent", "Agent")
        for agent in Agent.objects.all():
            step = cls.step_of(agent.workflow_json)
            if step is None:
                continue
            agent.workflow_json = {"nodes": [step], "edges": []}
            agent.save(update_fields=["workflow_json"])


class Migration(migrations.Migration):

    dependencies = [
        ('agent', '0006_agent_workflow_json'),
    ]

    operations = [
        migrations.RunPython(StartNode.forward, StartNode.backward),
    ]
