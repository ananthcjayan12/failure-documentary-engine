from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .models import MasterAsset, MasterAssetPlan, Shot, ShotPlan


STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "with", "in", "on", "at",
    "scene", "shot", "visual", "reusable", "support", "distinct", "chapter",
    "technically", "credible", "documentary", "clearly", "supports", "narration", "exact", "spoken", "beat",
}


def tokens(text: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in STOPWORDS
    }


def similarity(a: Shot, b: Shot) -> float:
    score = 0.0
    if a.visual_type == b.visual_type:
        score += 0.50
    ta = tokens(a.suggested_visual + " " + a.visual_purpose)
    tb = tokens(b.suggested_visual + " " + b.visual_purpose)
    if ta or tb:
        score += 0.35 * (len(ta & tb) / max(1, len(ta | tb)))
    if a.chapter_id == b.chapter_id:
        score += 0.10
    if a.suspense_function == b.suspense_function:
        score += 0.05
    return score


@dataclass
class Cluster:
    shots: list[Shot] = field(default_factory=list)

    @property
    def representative(self) -> Shot:
        return self.shots[0]


def category_for(shot: Shot, reuse_count: int) -> str:
    text = (shot.visual_type + " " + shot.suggested_visual).lower()
    if any(word in text for word in ["atmosphere", "ocean", "cloud", "rain", "room tone"]):
        return "atmosphere"
    if any(word in text for word in ["evidence", "investigation", "radar", "map", "sonar", "document"]):
        return "investigation"
    if reuse_count <= 1:
        return "story_specific"
    return "hero"


def optimize_shots(shot_plan: ShotPlan, maximum_assets: int) -> MasterAssetPlan:
    if maximum_assets < 1:
        raise ValueError("maximum_assets must be positive")
    clusters: list[Cluster] = []
    # Strong matches first.
    for shot in shot_plan.shots:
        best_cluster = None
        best_score = -1.0
        for cluster in clusters:
            score = max(similarity(shot, existing) for existing in cluster.shots)
            if score > best_score:
                best_score = score
                best_cluster = cluster
        # A shared media type, chapter, or generic "support" role is not enough
        # to make two narration beats visually interchangeable.  Hold out for a
        # strong semantic match until the asset budget is actually exhausted.
        threshold = 0.72 if len(clusters) < maximum_assets else -1.0
        if best_cluster is not None and best_score >= threshold:
            best_cluster.shots.append(shot)
        elif len(clusters) < maximum_assets:
            clusters.append(Cluster([shot]))
        else:
            assert best_cluster is not None
            best_cluster.shots.append(shot)

    # If initial clustering created too many due to future changes, merge smallest clusters.
    while len(clusters) > maximum_assets:
        smallest = min(clusters, key=lambda c: len(c.shots))
        clusters.remove(smallest)
        target = max(
            clusters,
            key=lambda c: max(similarity(smallest.representative, s) for s in c.shots),
        )
        target.shots.extend(smallest.shots)

    assets: list[MasterAsset] = []
    covered: set[str] = set()
    for index, cluster in enumerate(clusters, 1):
        representative = cluster.representative
        linked = [shot.shot_id for shot in cluster.shots]
        covered.update(linked)
        uses = Counter(shot.visual_purpose for shot in cluster.shots)
        title_words = representative.suggested_visual.strip().rstrip(".")
        title = title_words[:70] or f"Master Asset {index}"
        assets.append(
            MasterAsset(
                asset_id=f"A{index:02d}",
                title=title,
                category=category_for(representative, len(linked)),
                linked_shots=linked,
                primary_use=representative.visual_purpose,
                secondary_uses=[purpose for purpose, _ in uses.most_common()[1:5]],
                required_reuse_count=len(linked),
            )
        )
    uncovered = [shot.shot_id for shot in shot_plan.shots if shot.shot_id not in covered]
    return MasterAssetPlan(
        project_id=shot_plan.project_id,
        maximum_assets=maximum_assets,
        assets=assets,
        uncovered_shots=uncovered,
    )
