from __future__ import annotations

from .config_loader import PolicyConfig


class SecurityError(PermissionError):
    pass


def assert_sender_allowed(openid: str, policy: PolicyConfig) -> None:
    if policy.allowed_openids and openid not in policy.allowed_openids:
        raise SecurityError("Sender is not in QQ_ALLOWED_OPENIDS")


def assert_prompt_allowed(prompt: str, policy: PolicyConfig) -> None:
    lowered = prompt.lower()
    for term in policy.blocked_terms:
        if term.lower() in lowered:
            raise SecurityError(f"Blocked term found: {term}")
