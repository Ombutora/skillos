"""Instruction agent: answers learner questions grounded in the approved step text."""

from sqlalchemy.orm import Session

from app.ai import gateway
from app.skillgraph.schema import SkillGraph, Step

SYSTEM = """You are the instruction assistant in SkillOS. Answer the learner's question using ONLY the
approved procedure text provided. If the answer is not in it, say you don't know and suggest asking the
instructor. Never tell the learner to skip a step, bypass a safety requirement, or work on mains/high voltage.
Keep answers under 120 words."""


def approved_context(g: SkillGraph, step: Step) -> str:
    lines = [f"Skill: {g.title}", f"Current step: {step.title}", step.description]
    lines += [f"- {i}" for i in step.instructions]
    if step.safety.requirements:
        lines.append("Safety requirements: " + "; ".join(step.safety.requirements))
    for m in step.common_mistakes:
        lines.append(f"Common mistake: {m.description} → {m.correction}")
    return "\n".join(x for x in lines if x)


def answer(db: Session, org_id: str, g: SkillGraph, step: Step, question: str) -> dict:
    ctx = approved_context(g, step)
    try:
        reply = gateway.text(db, org_id=org_id, purpose="instruction", system=SYSTEM,
                             content=[gateway.text_part(f"Approved procedure:\n{ctx}\n\nLearner question: {question}")])
        return {"source": "ai", "answer": reply}
    except gateway.AINotConfigured:
        # Not an AI answer: the approved text itself, labelled as such.
        return {"source": "approved_skill_text", "answer": ctx,
                "note": "AI assistant is not configured; showing the approved step text."}
