"""Errors raised before the bot connects."""


class ConfigError(Exception):
    """Configuration or secrets are missing or invalid. The message names the key."""
