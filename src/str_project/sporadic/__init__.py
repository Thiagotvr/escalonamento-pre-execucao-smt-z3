"""Sporadic task extension (offline finite-horizon scenarios) for STR Project."""

from .adapter import adapt_sequence_to_instance, save_adapted_instance
from .generator import generate_sequence
from .models import (
    Activation,
    AdaptedSporadicInstance,
    CrossTaskRule,
    GeneratedSequence,
    ScenarioSpec,
    SegmentTemplate,
    TaskSpec,
    load_scenario_spec,
    parse_scenario_spec,
)
from .validation import (
    SporadicValidationError,
    validate_activations,
    validate_adapted_instance,
    validate_scenario_spec,
    validate_sporadic_schedule,
)

__all__ = [
    "Activation",
    "AdaptedSporadicInstance",
    "CrossTaskRule",
    "GeneratedSequence",
    "ScenarioSpec",
    "SegmentTemplate",
    "SporadicValidationError",
    "TaskSpec",
    "adapt_sequence_to_instance",
    "generate_sequence",
    "load_scenario_spec",
    "parse_scenario_spec",
    "save_adapted_instance",
    "validate_activations",
    "validate_adapted_instance",
    "validate_scenario_spec",
    "validate_sporadic_schedule",
]
