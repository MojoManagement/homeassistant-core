"""Model-specific LG soundbar capabilities."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LGSoundbarCapabilities:
    """Capabilities that differ between LG soundbar model families."""

    local_power_on: bool = True
    local_power_off: bool = True
    power_state_from_connect: bool = False


_DEFAULT_CAPABILITIES = LGSoundbarCapabilities()
_SP11RA_CAPABILITIES = LGSoundbarCapabilities(
    local_power_on=True,
    local_power_off=False,
    power_state_from_connect=True,
)
_MODEL_CAPABILITIES = {
    "SP11RA": _SP11RA_CAPABILITIES,
    "DSP11RA": _SP11RA_CAPABILITIES,
}


def capabilities_for_model(model: str | None) -> LGSoundbarCapabilities:
    """Return explicit capabilities for a model, preserving legacy defaults."""
    if model is None:
        return _DEFAULT_CAPABILITIES
    return _MODEL_CAPABILITIES.get(model.upper(), _DEFAULT_CAPABILITIES)
