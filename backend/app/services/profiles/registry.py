"""Registry mapping ``scoring_profile`` keys to resolver instances."""
from __future__ import annotations

import logging
from collections.abc import Mapping

from app.services.profiles.base import DerivedProfile, ProfileInputs, ProfileResolver
from app.services.profiles.ipip_ipc import IpipIpcResolver

logger = logging.getLogger(__name__)

PROFILE_RESOLVERS: Mapping[str, ProfileResolver] = {
    "ipip_ipc_v1": IpipIpcResolver(),
}


def resolve_profile(profile_key: str | None, inputs: ProfileInputs) -> DerivedProfile | None:
    """Run the resolver registered under ``profile_key``.

    Unknown keys are logged and skipped so a catalog misconfiguration never
    blocks a candidate submission.

    Args:
        profile_key: Assessment ``scoring_profile`` value (may be None/empty).
        inputs: Scoring output for the submitted assessment.

    Returns:
        The derived profile, or None when no (known) resolver applies.
    """
    key = (profile_key or "").strip()
    if not key:
        return None
    resolver = PROFILE_RESOLVERS.get(key)
    if resolver is None:
        logger.error("profile_resolver_unknown key=%s", key)
        return None
    return resolver.resolve(inputs)
