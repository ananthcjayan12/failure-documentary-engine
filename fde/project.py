from __future__ import annotations

from pathlib import Path

from .constants import STAGE_DIRECTORIES
from .io import load_model, write_json
from .models import ProjectBrief, ProjectManifest, ProjectState, utc_now


class ProjectStore:
    def __init__(self, workspace: Path | str = "projects") -> None:
        self.workspace = Path(workspace).resolve()

    def project_dir(self, project_id: str) -> Path:
        return self.workspace / project_id

    def exists(self, project_id: str) -> bool:
        return (self.project_dir(project_id) / "project_manifest.json").exists()

    def create(self, brief: ProjectBrief) -> Path:
        project = self.project_dir(brief.project_id)
        if project.exists() and any(project.iterdir()):
            raise FileExistsError(f"project already exists: {project}")
        project.mkdir(parents=True, exist_ok=True)
        for directory in STAGE_DIRECTORIES:
            (project / directory).mkdir(parents=True, exist_ok=True)
        write_json(project / "00_input/project_brief.json", brief)
        manifest = ProjectManifest(project_id=brief.project_id)
        write_json(project / "project_manifest.json", manifest)
        return project

    def brief(self, project_id: str) -> ProjectBrief:
        return load_model(self.project_dir(project_id) / "00_input/project_brief.json", ProjectBrief)

    def manifest(self, project_id: str) -> ProjectManifest:
        return load_model(self.project_dir(project_id) / "project_manifest.json", ProjectManifest)

    def save_manifest(self, manifest: ProjectManifest) -> None:
        manifest.updated_at = utc_now()
        write_json(self.project_dir(manifest.project_id) / "project_manifest.json", manifest)

    def transition(self, project_id: str, state: ProjectState) -> ProjectManifest:
        manifest = self.manifest(project_id)
        manifest.state = state
        self.save_manifest(manifest)
        return manifest

    def next_version(self, project_id: str, artifact: str) -> int:
        manifest = self.manifest(project_id)
        version = manifest.current_versions.get(artifact, 0) + 1
        manifest.current_versions[artifact] = version
        self.save_manifest(manifest)
        return version

    def approve_version(self, project_id: str, artifact: str, version: int | None = None) -> None:
        manifest = self.manifest(project_id)
        resolved = version or manifest.current_versions.get(artifact)
        if not resolved:
            raise ValueError(f"no current version for {artifact}")
        manifest.approved_versions[artifact] = resolved
        self.save_manifest(manifest)

    def invalidate(self, project_id: str, targets: list[str]) -> None:
        manifest = self.manifest(project_id)
        for target in targets:
            if target not in manifest.invalidated_targets:
                manifest.invalidated_targets.append(target)
        self.save_manifest(manifest)

    def clear_invalidation(self, project_id: str, targets: list[str]) -> None:
        manifest = self.manifest(project_id)
        manifest.invalidated_targets = [x for x in manifest.invalidated_targets if x not in targets]
        self.save_manifest(manifest)
