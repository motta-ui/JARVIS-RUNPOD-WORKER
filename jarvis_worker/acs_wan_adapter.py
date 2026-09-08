from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_GRADIO_ONLY = {
    "target", "image_mask_guide", "lset_name", "client_id", "api_name", "mode",
}


class WanAdapter:
    """Small independent bridge from JARVIS HTTP requests to WanGP's Python API."""

    def __init__(self, wan_dir: str | Path, config_path: str | Path | None = None,
                 output_dir: str | Path | None = None, cli_args=None):
        self.wan_dir = str(Path(wan_dir).resolve())
        self.config_path = str(Path(config_path).resolve()) if config_path else None
        self.output_dir = str(Path(output_dir).resolve()) if output_dir else None
        self.cli_args = tuple(cli_args or ("--attention", "sdpa", "--perc-reserved-mem-max", "0.5"))
        if self.wan_dir not in sys.path:
            sys.path.insert(0, self.wan_dir)
        self._session = None

    def _ensure(self):
        if self._session is None:
            from shared.api import WanGPSession
            self._session = WanGPSession(
                root=self.wan_dir,
                config_path=self.config_path,
                output_dir=self.output_dir,
                cli_args=self.cli_args,
            )
            self._session.ensure_ready()
        return self._session

    def close(self):
        if self._session is not None:
            try:
                self._session.close()
            finally:
                self._session = None

    def list_models(self) -> list[str]:
        defs = self._ensure().get_model_defs()
        if isinstance(defs, dict):
            return list(defs.keys())
        return [str(d.get("model_type")) for d in defs if isinstance(d, dict) and d.get("model_type")]

    def model_schema(self, model_type: str) -> dict[str, Any]:
        result = self._ensure().get_model_schema(model_type)
        if result is None:
            raise ValueError(f"Unknown model_type: {model_type}")
        return result

    def default_settings(self, model_type: str) -> dict[str, Any]:
        return self._ensure().get_default_settings(model_type)

    def availability(self, model_type: str) -> dict[str, Any]:
        return self._ensure().get_model_availability(model_type)

    def build_settings(self, model_type: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        settings = self.default_settings(model_type)
        for key, value in (overrides or {}).items():
            if key not in _GRADIO_ONLY:
                settings[key] = value
        settings["model_type"] = model_type
        return settings

    def generate(self, model_type: str, overrides: dict[str, Any] | None = None, callbacks=None) -> dict[str, Any]:
        settings = self.build_settings(model_type, overrides)
        job = self._ensure().submit_task(settings, callbacks=callbacks)
        result = job.result()
        if not result.success:
            errors = getattr(result, "errors", None) or []
            message = getattr(errors[0], "message", "unknown generation error") if errors else "unknown generation error"
            return {"ok": False, "error": message}

        generated = list(getattr(result, "generated_files", None) or [])
        artifacts = list(getattr(result, "artifacts", None) or [])
        path = None
        media_type = None
        fps = None
        if artifacts:
            first = artifacts[0]
            path = getattr(first, "path", None)
            media_type = getattr(first, "media_type", None)
            fps = getattr(first, "fps", None)
        if not path and generated:
            first = generated[0]
            path = getattr(first, "path", first)

        return {
            "ok": bool(path),
            "path": str(path) if path else None,
            "media_type": media_type,
            "fps": fps,
            "generated_files": [str(getattr(item, "path", item)) for item in generated],
        }
