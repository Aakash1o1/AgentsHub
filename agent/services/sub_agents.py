from agent.models import Agent


class SubAgentRules:
    MAX_LEVELS = 3

    @staticmethod
    def links(vendor):
        rows = Agent.sub_agents.through.objects.filter(from_agent__vendor=vendor)
        children = {}
        for parent, child in rows.values_list("from_agent_id", "to_agent_id"):
            children.setdefault(parent, []).append(child)
        return children

    @staticmethod
    def flipped(children):
        parents = {}
        for parent, kids in children.items():
            for kid in kids:
                parents.setdefault(kid, []).append(parent)
        return parents

    @classmethod
    def chain_length(cls, agent_id, links):
        return 1 + max((cls.chain_length(next_id, links) for next_id in links.get(agent_id, [])), default=0)

    @classmethod
    def reaches(cls, start, target, children):
        return start == target or any(cls.reaches(kid, target, children) for kid in children.get(start, []))

    @classmethod
    def check(cls, vendor, agent_id, sub_ids):
        labels = dict(vendor.agents.values_list("id", "label"))
        if any(sub_id not in labels for sub_id in sub_ids):
            return "A sub-agent must belong to this vendor."
        if agent_id in sub_ids:
            return "An agent cannot be its own sub-agent."

        children = cls.links(vendor)
        for sub_id in sub_ids:
            if agent_id is not None and cls.reaches(sub_id, agent_id, children):
                return f"{labels[sub_id]} already uses this agent, so adding it would create a loop."

        above = cls.chain_length(agent_id, cls.flipped(children))
        for sub_id in sub_ids:
            if above + cls.chain_length(sub_id, children) > cls.MAX_LEVELS:
                return f"Adding {labels[sub_id]} would make a chain longer than {cls.MAX_LEVELS} levels."
        return None
