"""kilonova exception types."""


class KilonovaError(Exception):
    """Base for all kilonova errors."""


class DesignError(KilonovaError):
    """The Design file is invalid or uses something kilonova does not support yet."""


class ConfigurationError(KilonovaError):
    """The configuration file is invalid against the Design."""
