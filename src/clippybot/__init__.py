"""Clippy Bot Metadata Info"""

import os
import sys
from importlib.metadata import metadata
from importlib.metadata._meta import PackageMetadata


def assert_env_param(
    env_name: str, env_message: str = "Environment Variable {} was not set!"
) -> any:
    """Load an environment variable or fail."""
    value = os.getenv(env_name)
    if value is None:
        raise AssertionError(env_message.replace("{}", env_name))
    return value


__metadata__: PackageMetadata = metadata(__name__)
__twitch_app_id__ = "qpdklwf93powtxpbf1skauebzvfpbu"
__twitch_app_secret__ = assert_env_param("CLIPPYBOT_SECRET")
