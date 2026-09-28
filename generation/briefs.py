from __future__ import annotations

from scoring.llm_client import generate_json

PROBE_SLOTS = 3


def _select_probes(score: dict, red_flags: list[dict], rubrics: dict) -> tuple[list[dict], list[dict]]:
    """Returns (static_red_flag_probes, criteria_needing_llm_probes). First the probe for each
    red flag present (in rubric order), then the lowest-scoring criteria fill the remaining slots."""
    flag_defs = {f["id"]: f for f in rubrics["red_flags"]["flags"]}
    present_ids = {f["id"] for f in red_flags if f.get("present")}

    static_probes = []
    for fid in ("F1", "F2", "F3", "F4"):
        if fid in present_ids and len(static_probes) < PROBE_SLOTS:
            fdef = flag_defs[fid]
            static_probes.append({"source": "red_flag", "id": fid, "text": fdef["probe"]})

    remaining = PROBE_SLOTS - len(static_probes)
    weak_criteria = []
    if remaining > 0:
        ranked = sorted(score["criteria"], key=lambda c: (c["score"], -c["weight"]))
        weak_criteria = ranked[:remaining]

    return static_probes, weak_criteria


def _build_prompt(score: dict, weak_criteria: list[dict], role_label: str) -> str:
    criteria_lines = "\n".join(
        f"- {c['name']} ({c['id']}): scored {c['score']}/5. Evidence: \"{c['evidence']}\". Rationale: {c['rationale']}"
        for c in score["criteria"]
    )
    weak_lines = "\n".join(f"- {c['name']} ({c['id']}): {c['rationale']}" for c in weak_criteria) or "None"

    return f"""You are drafting a short internal interview brief for Arjun, the hiring manager, about a
candidate scored {score['band']} for the {role_label} role at Kargo (a logistics SaaS company).

Per-criterion scores and evidence for this candidate on the {role_label} rubric:
{criteria_lines}

Weakest-scoring criteria selected for interview probing (write one open-ended question per item, grounded
in its rationale -- do not just restate the rationale as a statement):
{weak_lines}

Respond with ONLY a JSON object of this shape:
{{
  "why_ranked_here": "2-3 sentences citing specific evidence above, explaining why this candidate landed in the {score['band']} band",
  "biggest_gap": "1-2 sentences naming the single biggest gap, grounded in the lowest-scoring criterion above",
  "probes": ["one open-ended interview question per weak criterion listed above, in the same order; empty list if none listed"]
}}
Only reference facts given above. Do not invent CV details not present in the evidence/rationale shown."""


def generate_interview_brief(score: dict, red_flags: list[dict], rubrics: dict) -> dict:
    role_label = rubrics["roles"][score["role"]]["label"]
    static_probes, weak_criteria = _select_probes(score, red_flags, rubrics)

    prompt = _build_prompt(score, weak_criteria, role_label)
    result = generate_json(prompt)

    llm_probes = result.get("probes") or []
    generated_probes = [
        {"source": "criterion", "id": c["id"], "text": text}
        for c, text in zip(weak_criteria, llm_probes)
    ]

    return {
        "why_ranked_here": result["why_ranked_here"],
        "biggest_gap": result["biggest_gap"],
        "probes": (static_probes + generated_probes)[:PROBE_SLOTS],
    }
