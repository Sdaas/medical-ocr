"""Shared foundation for medical-ocr — the seam every backend and `compare`
depend on.

Provides four things (F1):

- **Envelope** — the hybrid extraction envelope (ADR-0002): fixed metadata plus
  a best-effort ``raw_text`` and an open ``fields`` dict. All three backends
  (VLM, Surya, Claude) fill the same shape so scoring can read them uniformly.
- **Timer / @timed** — duration measurement (C7), as a context manager and a
  decorator.
- **output_path / write_envelope** — output-file writer + path convention (C8):
  machine outputs land under a top-level ``output/`` tree that mirrors the
  image's location, named by technique (and model), so multiple backends/models
  never collide and generated files stay out of the committed input dir.
- **truth_path / locate_truth / validate_truth / load_truth** — ground-truth
  sidecar convention (ADR-0003): ``<image>.truth.json`` next to the image, with
  an explicit override, plus structural validation.

Standard library only — keeping `common` dependency-free is deliberate.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

# --------------------------------------------------------------------------- #
# Envelope (C4 / ADR-0002)
# --------------------------------------------------------------------------- #

# Fixed key order for the serialized envelope — matches ADR-0002.
_ENVELOPE_ORDER = (
    "filename",
    "technique",
    "model",
    "duration_sec",
    "durations",
    "timestamp",
    "raw_text",
    "fields",
)


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


@dataclass
class Envelope:
    """The shared extraction envelope (ADR-0002).

    ``model`` is ``None`` for pure OCR (e.g. Surya). ``fields`` is an open dict —
    the medical taxonomy is a convention to converge, not a hard schema.

    ``duration_sec`` is the total wall-clock for the run. ``durations`` is an
    optional per-call breakdown for backends that make more than one model call
    (e.g. VLM's transcribe + extract → ``{"transcribe": …, "extract": …}``); it
    stays empty for single-call/pure-OCR backends, so every envelope keeps the
    same shape.
    """

    filename: str
    technique: str  # "vlm" | "surya" | "claude"
    model: str | None
    raw_text: str
    fields: dict[str, Any]
    duration_sec: float = 0.0
    durations: dict[str, float] = field(default_factory=dict)
    timestamp: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict in the ADR-0002 key order."""
        d = asdict(self)
        return {key: d[key] for key in _ENVELOPE_ORDER}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Envelope:
        """Rebuild an Envelope from a dict, ignoring unknown keys."""
        known = {f.name for f in dataclass_fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


# --------------------------------------------------------------------------- #
# Timer (C7)
# --------------------------------------------------------------------------- #


class Timer:
    """Context manager that measures wall-clock seconds.

    Usage::

        with Timer() as t:
            run_backend(...)
        env = Envelope(..., duration_sec=t.duration_sec)
    """

    def __init__(self) -> None:
        self.duration_sec: float = 0.0
        self._start: float = 0.0

    def __enter__(self) -> Timer:
        self._start = perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.duration_sec = perf_counter() - self._start


def timed(func: Callable[..., Any]) -> Callable[..., tuple[Any, float]]:
    """Decorator that returns ``(result, duration_sec)`` for ``func``.

    Built on :class:`Timer`, so the two share one measurement path.
    """

    def wrapper(*args: Any, **kwargs: Any) -> tuple[Any, float]:
        with Timer() as t:
            result = func(*args, **kwargs)
        return result, t.duration_sec

    return wrapper


# --------------------------------------------------------------------------- #
# Output path + writer (C8)
# --------------------------------------------------------------------------- #

# Top-level directory for all machine-generated outputs — never committed (its
# contents are gitignored), so it stays separate from the curated, committed
# inputs and ground-truth sidecars in the image dir.
OUTPUT_ROOT = "output"


def _sanitize_model(model: str) -> str:
    """Make a LiteLLM model id safe for a filename.

    LiteLLM/Ollama ids carry provider slashes and version tags —
    ``ollama/llava:7b`` — neither of which is filename-safe (``:`` is remapped by
    Finder on macOS). Collapse any run of unsafe characters to a single ``-``.
    """
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-")


def _mirrored_parent(image_path: Path, base: Path) -> Path:
    """The image's parent dir expressed relative to ``base`` for mirroring.

    When the image lives under ``base`` (the common case: run from the repo
    root), this is its sub-path — e.g. ``sample-data``. When it lives outside
    ``base``, we drop the filesystem anchor and mirror the rest, so distinct
    inputs never collide under the output root.
    """
    parent = image_path.parent.resolve()
    try:
        return parent.relative_to(base.resolve())
    except ValueError:
        tail = parent.parts[1:]  # drop drive/root anchor
        return Path(*tail) if tail else Path()


def output_path(
    image_path: str | Path,
    technique: str,
    model: str | None = None,
    *,
    base: str | Path | None = None,
    output_root: str | Path | None = None,
) -> Path:
    """Where a backend's envelope for ``image_path`` should be written.

    Convention (C8): outputs go under a top-level ``output/`` tree that mirrors
    the image's location, as
    ``output/<image_parent_rel>/<stem>.<technique>[.<model>].json``. Keeping all
    generated files under one wholesale-gitignored root keeps the curated input
    dir (images + truth sidecars) clean and committable.

    The model segment is omitted when ``model`` is None (pure OCR) and has
    filesystem-unsafe characters sanitized. ``base`` is the directory image
    paths are mirrored relative to (default: current working dir); ``output_root``
    overrides the top-level ``output/`` location (default: ``output`` under cwd).
    """
    image_path = Path(image_path)
    parts = [image_path.stem, technique]
    if model is not None:
        parts.append(_sanitize_model(model))
    name = ".".join(parts) + ".json"

    root = Path(output_root) if output_root is not None else Path(OUTPUT_ROOT)
    base_dir = Path(base) if base is not None else Path.cwd()
    return root / _mirrored_parent(image_path, base_dir) / name


def write_envelope(
    env: Envelope,
    image_path: str | Path,
    *,
    base: str | Path | None = None,
    output_root: str | Path | None = None,
) -> Path:
    """Write ``env`` as pretty JSON to its conventional output path.

    Creates the mirrored output directory if needed. Returns the path written.
    """
    dest = output_path(image_path, env.technique, env.model, base=base, output_root=output_root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(env.to_dict(), indent=2, ensure_ascii=False))
    return dest


# --------------------------------------------------------------------------- #
# Ground truth (C5 / ADR-0003)
# --------------------------------------------------------------------------- #

TRUTH_SUFFIX = ".truth.json"


class TruthValidationError(ValueError):
    """A ground-truth sidecar is missing, unparseable, or the wrong shape."""


def truth_path(image_path: str | Path) -> Path:
    """The sidecar truth path for an image: ``<image>.truth.json`` beside it."""
    image_path = Path(image_path)
    return image_path.with_name(image_path.stem + TRUTH_SUFFIX)


def locate_truth(
    image_path: str | Path,
    override: str | Path | None = None,
) -> Path | None:
    """Find the ground-truth file for ``image_path`` (ADR-0003).

    An explicit ``override`` wins — but if it is given and does not exist, that
    is a user error and raises ``FileNotFoundError``. Otherwise returns the
    sidecar path if it exists, else ``None`` (no truth authored yet).
    """
    if override is not None:
        override = Path(override)
        if not override.exists():
            raise FileNotFoundError(f"ground-truth override not found: {override}")
        return override

    sidecar = truth_path(image_path)
    return sidecar if sidecar.exists() else None


def validate_truth(path: str | Path) -> dict[str, Any]:
    """Structurally validate a ground-truth file and return its parsed contents.

    Checks (per ADR-0003, which leaves truth metadata optional): the file
    exists, parses as JSON, is a JSON object, and carries a ``fields`` dict —
    the one thing ``compare`` relies on. Raises ``TruthValidationError`` with a
    message naming the file and the specific problem otherwise.
    """
    path = Path(path)
    if not path.exists():
        raise TruthValidationError(f"ground-truth file not found: {path}")

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise TruthValidationError(f"ground-truth is not valid JSON: {path} ({exc})") from exc

    if not isinstance(data, dict):
        raise TruthValidationError(f"ground-truth must be a JSON object: {path}")
    if "fields" not in data:
        raise TruthValidationError(f"ground-truth is missing a 'fields' key: {path}")
    if not isinstance(data["fields"], dict):
        raise TruthValidationError(f"ground-truth 'fields' must be an object: {path}")

    return data


def load_truth(
    image_path: str | Path,
    override: str | Path | None = None,
) -> dict[str, Any]:
    """Locate and validate the ground truth for an image in one call.

    Raises ``TruthValidationError`` if no truth file can be located, or if the
    located file fails validation.
    """
    located = locate_truth(image_path, override=override)
    if located is None:
        raise TruthValidationError(
            f"no ground-truth file for image: {image_path} "
            f"(expected sidecar {truth_path(image_path)})"
        )
    return validate_truth(located)
