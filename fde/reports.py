from __future__ import annotations

from .models import DocumentaryScript, DocumentaryStructure, ResearchDossier, ShotSkeletonPlan


def research_markdown(dossier: ResearchDossier) -> str:
    lines = [f"# Research Dossier — {dossier.project_id}", "", dossier.summary, "", "## Timeline"]
    lines.extend(f"- {item}" for item in dossier.timeline)
    lines += ["", "## Evidence"]
    lines.extend(f"- {item}" for item in dossier.evidence)
    lines += ["", "## Claim Ledger", "", "| ID | Status | Statement | Allowed wording |", "|---|---|---|---|"]
    for claim in dossier.claims:
        lines.append(f"| {claim.claim_id} | {claim.status} | {claim.statement} | {claim.allowed_language} |")
    lines += ["", "## Sources"]
    for source in dossier.sources:
        detail = f" — {source.url}" if source.url else ""
        lines.append(f"- **{source.source_id}:** {source.title}{detail}")
    return "\n".join(lines).rstrip() + "\n"


def structure_markdown(structure: DocumentaryStructure) -> str:
    lines = [f"# {structure.title} — Documentary Structure", ""]
    for chapter in structure.chapters:
        lines += [
            f"## {chapter.chapter_id} — {chapter.title} ({chapter.start_target:.0f}–{chapter.end_target:.0f}s)",
            "", f"**Purpose:** {chapter.narrative_purpose}",
            f"**Opening question:** {chapter.opening_question}", "", "**Key information:**",
            *[f"- {item}" for item in chapter.key_information], "",
            f"**Reveal:** {chapter.reveal}", f"**Ending hook:** {chapter.ending_hook}", "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def script_markdown(script: DocumentaryScript) -> str:
    lines = [f"# {script.title} — Narration Script", "", f"Estimated duration: {script.estimated_total_seconds:.1f}s  ", f"Estimated words: {script.estimated_word_count}", ""]
    current = None
    for segment in script.segments:
        if segment.chapter_id != current:
            current = segment.chapter_id
            lines += [f"## {current}", ""]
        claim_text = ", ".join(segment.claim_ids) or "none"
        lines += [
            f"### {segment.narration_id} · {segment.estimated_start:.1f}s · {segment.estimated_duration:.1f}s",
            "", segment.text, "", f"*Mood: {segment.mood} · intensity {segment.intensity:.2f} · claims: {claim_text}*", "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def shots_markdown(plan: ShotSkeletonPlan) -> str:
    lines = [f"# Shot Skeleton — {plan.project_id}", "", "| Shot | Time | Chapter | Story function | Visual purpose |", "|---|---:|---|---|---|"]
    for shot in plan.shots:
        lines.append(
            f"| {shot.shot_id} | {shot.start:.1f}–{shot.start + shot.duration:.1f}s | {shot.chapter_id} | "
            f"{shot.story_function} | {shot.visual_purpose} |"
        )
    return "\n".join(lines).rstrip() + "\n"
