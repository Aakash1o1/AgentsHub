from django.db import migrations, models


class WorkflowCopy:
    START = {"x": 40, "y": 200}

    @classmethod
    def forward(cls, apps, schema_editor):
        Agent = apps.get_model("agent", "Agent")
        for agent in Agent.objects.all():
            position = (agent.graph_json or {}).get("agent") or cls.START
            agent.workflow_json = {
                "nodes": [{
                    "id": "step-1",
                    "type": "step",
                    "position": {"x": position["x"], "y": position["y"]},
                    "data": {
                        "name": agent.prompt_name,
                        "tools": list(agent.tools or []),
                        "force_tool_call": agent.force_tool_call,
                    },
                }],
                "edges": [],
            }
            agent.save(update_fields=["workflow_json"])

    @classmethod
    def backward(cls, apps, schema_editor):
        Agent = apps.get_model("agent", "Agent")
        for agent in Agent.objects.all():
            nodes = (agent.workflow_json or {}).get("nodes") or [{}]
            step = nodes[0]
            data = step.get("data") or {}
            agent.prompt_name = data.get("name", "")
            agent.tools = data.get("tools", [])
            agent.force_tool_call = data.get("force_tool_call", False)
            agent.graph_json = {"agent": step.get("position") or cls.START, "tools": []}
            agent.save(update_fields=["prompt_name", "tools", "force_tool_call", "graph_json"])


class Migration(migrations.Migration):

    dependencies = [
        ('agent', '0005_agent_force_tool_call'),
    ]

    operations = [
        migrations.AddField(
            model_name='agent',
            name='workflow_json',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(WorkflowCopy.forward, WorkflowCopy.backward),
        migrations.RemoveField(model_name='agent', name='force_tool_call'),
        migrations.RemoveField(model_name='agent', name='graph_json'),
        migrations.RemoveField(model_name='agent', name='prompt_name'),
        migrations.RemoveField(model_name='agent', name='tools'),
    ]
