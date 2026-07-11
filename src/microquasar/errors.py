"""microquasar exception types."""


class MicroquasarError(Exception):
    """Base for all microquasar errors."""


class DesignError(MicroquasarError):
    """The Design file is invalid or uses something microquasar does not support yet."""


class ConfigurationError(MicroquasarError):
    """The configuration file is invalid against the Design."""
