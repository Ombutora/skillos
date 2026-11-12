import networkx as nx

from app.skillgraph.schema import SkillGraph


def to_networkx(g: SkillGraph) -> nx.DiGraph:
    """Step nodes plus tool/hazard nodes. Edges: transitions, prerequisites, uses_tool, has_hazard."""
    d = nx.DiGraph()
    for s in g.steps:
        d.add_node(s.step_id, node_type="step", kind=s.kind, critical=s.safety.critical, terminal=s.terminal)
    for s in g.steps:
        for t in s.transitions:
            d.add_edge(s.step_id, t.to, relation="transition", condition=t.condition.type, label=t.label)
        for p in s.prerequisites:
            if not d.has_edge(p, s.step_id):
                d.add_edge(p, s.step_id, relation="prerequisite")
        for tool in s.required_tools:
            d.add_node(f"tool:{tool}", node_type="tool")
            d.add_edge(s.step_id, f"tool:{tool}", relation="uses_tool")
        for h in s.safety.hazards:
            d.add_node(f"hazard:{h}", node_type="hazard")
            d.add_edge(s.step_id, f"hazard:{h}", relation="has_hazard")
    return d


def flow_graph(g: SkillGraph) -> nx.DiGraph:
    """Only step→step transitions; used for reachability and path analysis."""
    d = nx.DiGraph()
    d.add_nodes_from(s.step_id for s in g.steps)
    for s in g.steps:
        for t in s.transitions:
            d.add_edge(s.step_id, t.to, condition=t.condition.type)
    return d


def happy_path(g: SkillGraph) -> list[str]:
    """Follow 'verified'/'always'/'measurement_in_range' edges from the entry step."""
    path, cur, seen = [], g.entry_step, set()
    while cur and cur not in seen:
        seen.add(cur)
        path.append(cur)
        step = g.step(cur)
        nxt = next(
            (t.to for t in step.transitions if t.condition.type in ("verified", "always", "measurement_in_range")),
            None,
        )
        cur = nxt
    return path
