import os
import sys

__dist_name__ = "obs-media-triggers"
__description__ = "A web app for controlling local media in OBS."
__author__ = "Ivo Robotnic"
__copyright__ = __author__
__license__ = "MIT"

__app_secret_env__ = "OMT_APP_SECRET"

__app_id__ = "jxihm8y9aqx3k4gj5j08l1msd71d3v"
__app_secret__ = os.getenv(__app_secret_env__)
__app_host__ = "localhost"
__app_port__ = 7032

if sys.version_info[:2] >= (3, 8):
    from importlib.metadata import PackageNotFoundError, version
else:
    from importlib_metadata import PackageNotFoundError, version

if __app_secret__ is None:
    raise RuntimeError(
        f"Environment variable {__app_secret_env__} must be defined before launching the app."
        " Find app secret at -> https://dev.twitch.tv/console/"
    )

try:
    __version__ = version(__dist_name__)
except PackageNotFoundError:
    __version__ = "unknown"
finally:
    del version, PackageNotFoundError
