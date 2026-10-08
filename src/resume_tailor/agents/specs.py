"""The five agents (spec-02 §3).

Prompts live in `prompts/*.md` as editable files rather than string literals,
because prompt tuning is the actual work in this system and needing to edit
Python to reword a sentence is friction that stops it happening.

Model assignment comes from config (OQ-6). The default is the backend's, with
one exception worth stating here rather than burying: the **Validator** should
get the strongest model available, not the cheapest. Selection and writing
degrade visibly — a missed fact shows on the review screen, weak prose reads as
bland. A weak Validator degrades invisibly: it rationalises an unsupported
claim as supported, and the candidate finds out in an interview.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from ..config import ModelConfig
from ..runtime.base import AgentSpec

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

#: Pipeline order. Selector and Recall run concurrently; the rest are
#: sequential (spec-02 §4).
AGENT_NAMES = ("analyst", "selector", "recall", "writer", "validator")


@cache
def load_prompt(name: str) -> str:
    path = PROMPT_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"no prompt for agent {name!r} at {path}")
    return path.read_text(encoding="utf-8").strip()


REQUIREMENTS_SCHEMA = {
    "type": "object",
    "required": ["requirements"],
    "properties": {
        "role_title": {"type": "string"},
        "seniority": {"type": "string"},
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "text", "kind"],
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "kind": {"enum": ["required", "preferred", "implicit"]},
                    "source": {"enum": ["explicit", "inferred"]},
                    "quote": {"type": "string"},
                },
            },
        },
        "signals": {"type": "object"},
    },
}

SELECTION_SCHEMA = {
    "type": "object",
    # `considered_and_rejected` is required, not optional. It is the audit
    # trail that proves a fact was read and judged rather than never seen.
    "required": ["selected", "considered_and_rejected"],
    "properties": {
        "selected": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["fact_id", "reason"],
                "properties": {
                    "fact_id": {"type": "string"},
                    "requirement_ids": {"type": "array", "items": {"type": "string"}},
                    "strength": {"enum": ["strong", "moderate", "weak"]},
                    "reason": {"type": "string"},
                    "depth": {"enum": ["expert", "working", "exposure"]},
                },
            },
        },
        "considered_and_rejected": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["fact_id", "reason"],
                "properties": {
                    "fact_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
    },
}

RECALL_SCHEMA = {
    "type": "object",
    "required": ["additions"],
    "properties": {
        "additions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["fact_id", "argument"],
                "properties": {
                    "fact_id": {"type": "string"},
                    "requirement_ids": {"type": "array", "items": {"type": "string"}},
                    "argument": {"type": "string"},
                },
            },
        },
        "tag_proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["fact_id", "add_tags"],
                "properties": {
                    "fact_id": {"type": "string"},
                    "add_tags": {"type": "array", "items": {"type": "string"}},
                    "why": {"type": "string"},
                },
            },
        },
        "concurrences": {"type": "array", "items": {"type": "string"}},
    },
}

DRAFT_SCHEMA = {
    "type": "object",
    "required": ["sections"],
    "properties": {
        "summary": {"type": "string"},
        "summary_sources": {"type": "array", "items": {"type": "string"}},
        "reply": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["kind", "bullets"],
                "properties": {
                    "kind": {"type": "string"},
                    "role_id": {"type": "string"},
                    "bullets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["text", "sources"],
                            "properties": {
                                "lead": {"type": "string"},
                                "text": {"type": "string"},
                                "sources": {"type": "array", "items": {"type": "string"}},
                                "metrics_used": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                    },
                },
            },
        },
        "skills": {"type": "array"},
    },
}

VALIDATION_SCHEMA = {
    "type": "object",
    "required": ["verdict", "clean"],
    "properties": {
        "verdict": {"enum": ["clean", "changes_made"]},
        "clean": {"type": "boolean"},
        "cuts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["bullet", "reason"],
                "properties": {
                    "bullet": {"type": "string"},
                    "section": {"type": "string"},
                    "reason": {"type": "string"},
                    "replacement": {"type": ["string", "null"]},
                },
            },
        },
        "warnings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["bullet", "reason"],
                "properties": {
                    "bullet": {"type": "string"},
                    "section": {"type": "string"},
                    "kind": {"enum": ["depth", "nda", "metric", "phrasing"]},
                    "reason": {"type": "string"},
                },
            },
        },
    },
}

CURATOR_SCHEMA = {
    "type": "object",
    "required": ["reply", "proposals"],
    "properties": {
        "reply": {"type": "string"},
        "questions": {"type": "array", "items": {"type": "string"}},
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["op", "type", "id"],
                "properties": {
                    "op": {"enum": ["create", "update"]},
                    "type": {"type": "string"},
                    "id": {"type": "string"},
                    "reason": {"type": "string"},
                    "fields": {"type": "object"},
                    "add_tags": {"type": "array", "items": {"type": "string"}},
                    "add_metrics": {"type": "array"},
                    "body": {"type": "string"},
                    "body_append": {"type": "string"},
                },
            },
        },
    },
}

SCHEMAS = {
    "analyst": REQUIREMENTS_SCHEMA,
    "selector": SELECTION_SCHEMA,
    "recall": RECALL_SCHEMA,
    "writer": DRAFT_SCHEMA,
    "validator": VALIDATION_SCHEMA,
    # Not part of a tailoring run, so not in AGENT_NAMES: it maintains the
    # knowledge base from a conversation (AC-R13.2) and proposes, never writes.
    "curator": CURATOR_SCHEMA,
}


def build_spec(name: str, models: ModelConfig | None = None) -> AgentSpec:
    if name not in SCHEMAS:
        raise ValueError(
            f"unknown agent {name!r}; expected one of: {', '.join([*AGENT_NAMES, 'curator'])}"
        )
    models = models or ModelConfig()
    return AgentSpec(
        name=name,
        system_prompt=load_prompt(name),
        model=models.for_agent(name),
        output_schema=SCHEMAS[name],
        # The Validator is the one that degrades invisibly (spec-06 §6).
        requires_strong_model=(name == "validator"),
    )


def build_all(models: ModelConfig | None = None) -> dict[str, AgentSpec]:
    return {name: build_spec(name, models) for name in AGENT_NAMES}
