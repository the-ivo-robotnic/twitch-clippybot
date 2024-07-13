from asyncio import run
from argparse import ArgumentParser, Namespace
from logging import ERROR, INFO, NOTSET, basicConfig, getLogger
from os import getcwd

from . import (
    __app_id__,
    __app_secret__,
    __app_host__,
    __app_port__,
    __description__,
    __dist_name__,
    __version__,
)
from .dashboard import Dashboard

from twitchAPI.twitch import Twitch
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.type import AuthScope, ChatEvent
from twitchAPI.chat import Chat, EventData, ChatMessage, ChatSub, ChatCommand, JoinedEvent
from spellchecker import SpellChecker

LOG = getLogger(__name__)
API_SCOPES = [AuthScope.CHAT_READ, AuthScope.CHAT_EDIT]
TARGET_CHANNEL = "the_ivo_robotnic"
SPELLCHECKER = SpellChecker()


def parse_args() -> Namespace:
    """Parse command line parameters

    Returns:
      :obj:`argparse.Namespace`: command line parameters namespace
    """
    parser = ArgumentParser(prog=__dist_name__, description=__description__)
    parser.add_argument(
        "--version",
        action="version",
        version=f"{__dist_name__} {__version__}",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        dest="log_level",
        metavar="Log Level",
        action="store_const",
        const=INFO,
        help="Set log level to WARN.",
    )
    parser.add_argument(
        "-vv",
        "--very-verbose",
        dest="log_level",
        metavar="Log Level",
        action="store_const",
        const=NOTSET,
        help="Set log level to DEBUG.",
    )
    return parser.parse_args()


async def on_join(event: JoinedEvent) -> None:
    await event.chat.send_message(
        room=event.room_name, text=f"Hi, my name is {event.user_name}, I'm here to help. :)"
    )


async def on_message(event: ChatMessage) -> None:
    message_words = event.text.split(" ")
    misspelled = SPELLCHECKER.unknown(message_words)
    misspelled_cnt = len(misspelled)
    LOG.info(
        "Found %s potential errors in message from %s: %s",
        misspelled_cnt,
        event.user.display_name,
        event.text,
    )

    if misspelled_cnt > 0:
        corrections = ", ".join(
            list(map(lambda x: f"\"{x}\" (did you mean \"{SPELLCHECKER.correction(x)}\"?)", misspelled))
        )
        await event.reply(
            f"Uh-oh, looks like you misspelled {corrections}"
            " Would you like help with that?"
            " (I am a bot, this action was performed automatically, "
            "if you would like me to ignore you, just type !ignore)"
        )


async def main():
    # Parse CMD Line Args
    args = parse_args()

    # Configure App
    log_level = ERROR if (args.log_level is None) else args.log_level
    debug = log_level == NOTSET
    basicConfig(level=log_level)

    twitch = await Twitch(__app_id__, __app_secret__)
    auth = UserAuthenticator(twitch=twitch, scopes=API_SCOPES, force_verify=False)
    access, refresh = await auth.authenticate()
    await twitch.set_user_authentication(
        token=access, scope=API_SCOPES, refresh_token=refresh, validate=False
    )

    chat = await Chat(twitch=twitch, initial_channel=[TARGET_CHANNEL])
    chat.register_event(ChatEvent.JOINED, on_join)
    chat.register_event(ChatEvent.MESSAGE, on_message)
    LOG.info("Starting twitch bot...")
    chat.start()

    try:
        input("Press any key to stop!\n")
    finally:
        chat.stop()
        await twitch.close()


if __name__ == "__main__":
    run(main())
