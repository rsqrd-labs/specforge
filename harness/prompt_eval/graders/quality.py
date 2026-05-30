from __future__ import annotations

import re

from prompt_eval.graders.common import make_result


def _section_body(artifact_md: str, heading: str) -> str:
    start = artifact_md.find(heading)
    if start < 0:
        return ""
    rest = artifact_md[start + len(heading) :]
    end = re.search(r"\n##\s+", rest)
    return rest[: end.start()] if end else rest


def deprecated_api_hit_count(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str],
):
    """quality: deprecated runtime, SDK, or LLM family choices are absent."""

    patterns = [
        r"\bPython\s*(?:<=|<|=)?\s*3\.10\b",
        r"\bNode(?:\.js)?\s*(?:<=|<|=)?\s*18\b",
        r"\bgpt-3(?:\.5)?\b",
        r"\bgemini-1\.",
        r"\bclaude-[12](?:\.|\b)",
    ]
    hits: list[str] = []
    for pattern in patterns:
        hits.extend(re.findall(pattern, artifact_md, flags=re.IGNORECASE))
    return make_result(
        name="deprecated_api_hit_count",
        axis="quality",
        score=1.0 / (1 + len(hits)),
        findings=[f"Deprecated choice mentioned: {hit}" for hit in hits[:10]],
        metadata={"hit_count": len(hits)},
    )


def banned_phrase_hit_count(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str],
):
    """quality: low-specificity and placeholder phrases are absent."""

    patterns = [
        r"\bTBD\b",
        r"\bTODO\b",
        r"\bFIXME\b",
        r"\bbest effort\b",
        r"\bhandle errors\b",
        r"\bsecure the endpoint\b",
        r"\bplaceholder\b",
        r"\bpass\s*(?:#.*)?$",
    ]
    hits: list[str] = []
    for pattern in patterns:
        hits.extend(
            re.findall(pattern, artifact_md, flags=re.IGNORECASE | re.MULTILINE)
        )
    return make_result(
        name="banned_phrase_hit_count",
        axis="quality",
        score=1.0 / (1 + len(hits)),
        findings=[f"Banned phrase hit: {hit}" for hit in hits[:10]],
        metadata={"hit_count": len(hits)},
    )


def adr_completeness_pct(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str],
):
    """quality: top-five ADRs include the five required lines."""

    if stage_type != "plan":
        return make_result(name="adr_completeness_pct", axis="quality", score=1.0)

    body = _section_body(artifact_md, "## Architecture Decision Records")
    entries = [
        entry for entry in re.split(r"(?m)^###\s+ADR-\d+\s+", body) if entry.strip()
    ]
    required = [
        "Decision:",
        "Forces:",
        "Options Considered:",
        "Chosen + WHY-not-next-best:",
        "Reversal Cost:",
    ]
    if not entries:
        return make_result(
            name="adr_completeness_pct",
            axis="quality",
            score=0.0,
            findings=["No ADR entries found."],
            metadata={"adr_count": 0},
        )

    complete_lines = 0
    missing: list[str] = []
    for index, entry in enumerate(entries, start=1):
        for label in required:
            if label in entry:
                complete_lines += 1
            else:
                missing.append(f"ADR-{index:03d} missing {label}")
    expected_lines = max(5, len(entries)) * len(required)
    score = complete_lines / expected_lines
    if len(entries) < 5:
        missing.append("Fewer than five ADRs present.")
    return make_result(
        name="adr_completeness_pct",
        axis="quality",
        score=score,
        findings=missing[:10],
        metadata={"adr_count": len(entries), "missing_lines": len(missing)},
    )


def frontend_section_presence_when_applicable(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str],
):
    """quality: browser-facing plans include Frontend Architecture."""

    if stage_type != "plan":
        return make_result(
            name="frontend_section_presence_when_applicable",
            axis="quality",
            score=1.0,
        )

    combined = " ".join([artifact_md, *deps.values()])
    applicable = bool(
        re.search(
            r"\b(frontend|browser|web UI|dashboard|screen|page)\b",
            combined,
            re.I,
        )
    )
    present = "## Frontend Architecture" in artifact_md
    return make_result(
        name="frontend_section_presence_when_applicable",
        axis="quality",
        score=1.0 if (not applicable or present) else 0.0,
        findings=[] if (not applicable or present) else ["Frontend plan is missing."],
        metadata={"applicable": int(applicable)},
    )


def capacity_model_presence(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str],
):
    if stage_type != "plan":
        return make_result(name="capacity_model_presence", axis="quality", score=1.0)
    body = _section_body(artifact_md, "## Capacity Model")
    required = ["Target RPS", "p95", "p99", "Data growth", "10x", "100x"]
    missing = [token for token in required if token.lower() not in body.lower()]
    return make_result(
        name="capacity_model_presence",
        axis="quality",
        score=(len(required) - len(missing)) / len(required),
        findings=[f"Capacity Model missing {token}" for token in missing],
    )


def stride_presence(stage_type: str, artifact_md: str, deps: dict[str, str]):
    if stage_type != "plan":
        return make_result(name="stride_presence", axis="quality", score=1.0)
    body = _section_body(artifact_md, "## Threat Model")
    required = [
        "Spoofing",
        "Tampering",
        "Repudiation",
        "Information disclosure",
        "Denial of service",
        "Elevation of privilege",
    ]
    missing = [token for token in required if token not in body]
    return make_result(
        name="stride_presence",
        axis="quality",
        score=(len(required) - len(missing)) / len(required),
        findings=[f"STRIDE missing {token}" for token in missing],
    )


def slo_presence(stage_type: str, artifact_md: str, deps: dict[str, str]):
    if stage_type != "plan":
        return make_result(name="slo_presence", axis="quality", score=1.0)
    body = _section_body(artifact_md, "## SLOs and Error Budgets")
    required = ["Availability", "Latency", "Correctness", "Error budget", "Paging"]
    missing = [token for token in required if token.lower() not in body.lower()]
    return make_result(
        name="slo_presence",
        axis="quality",
        score=(len(required) - len(missing)) / len(required),
        findings=[f"SLO section missing {token}" for token in missing],
    )


def fmea_presence(stage_type: str, artifact_md: str, deps: dict[str, str]):
    if stage_type != "plan":
        return make_result(name="fmea_presence", axis="quality", score=1.0)
    body = _section_body(artifact_md, "## Failure Mode and Effects Analysis")
    required = [
        "Failure mode",
        "Detection",
        "Blast radius",
        "Mitigation",
        "Recovery time",
        "Customer impact",
    ]
    missing = [token for token in required if token.lower() not in body.lower()]
    return make_result(
        name="fmea_presence",
        axis="quality",
        score=(len(required) - len(missing)) / len(required),
        findings=[f"FMEA missing {token}" for token in missing],
    )
