"""Data-driven marketplace registry."""

from .registry import (
    PlatformConfig,
    canonical_platform_id,
    get_platform,
    load_registry,
    platforms_in_scope,
    source_depth,
)

__all__ = [
    "PlatformConfig",
    "canonical_platform_id",
    "get_platform",
    "load_registry",
    "platforms_in_scope",
    "source_depth",
]
