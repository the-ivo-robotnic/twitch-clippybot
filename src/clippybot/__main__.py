from json import load, dump
from asyncio import run
from argparse import ArgumentParser, Namespace
from logging import ERROR, INFO, NOTSET, basicConfig, getLogger
from os import getcwd
from functools import partial

from . import (
    __app_id__,
    __app_secret__,
    __app_host__,
    __app_port__,
    __description__,
    __dist_name__,
    __version__,
)

from threading import Event, Lock
from twitchAPI.twitch import Twitch
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.type import AuthScope, ChatEvent
from twitchAPI.chat import Chat, EventData, ChatMessage, ChatUser, ChatCommand, JoinedEvent
from spellchecker import SpellChecker
from typing import List

LOG = getLogger(__name__)
API_SCOPES = [AuthScope.CHAT_READ, AuthScope.CHAT_EDIT]
SPELLCHECKER = SpellChecker()
IGNORE_USERS = []
IGNORE_USERS_LCK = Lock()
LISTEN = Event()


def load_ignore_users(cfg_path: str) -> List[str]:
    try:
        with open(cfg_path, "r") as file:
            data = load(file)
            ignored_users = data.get("ignore-users")
            return [] if ignored_users is None else ignored_users
    except FileNotFoundError as e:
        LOG.warning("No config found: %s", cfg_path)
        return []


def save_ignore_users(cfg_path: str, ignore_users: List[str] = []) -> None:
    with open(cfg_path, "w+") as file:
        data = {"ignore-users": ignore_users}
        dump(data, file)


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
    parser.add_argument(
        "-c",
        "--twitch-channel",
        dest="twitch_channel",
        metavar="Twitch Channel",
        type=str,
        default="the_ivo_robotnic",
        help="Twitch Channel to connect to.",
    )
    parser.add_argument(
        "-l",
        "--ignore-users-config",
        dest="ignore_users",
        metavar="Ignore Users Config File",
        type=str,
        default="ignore-users.json",
        help="Path to file storing users to ignore.",
    )
    return parser.parse_args()


def user_is_ignored(user: ChatUser) -> bool:
    IGNORE_USERS_LCK.acquire()
    is_ignored = user.id in IGNORE_USERS
    IGNORE_USERS_LCK.release()
    return is_ignored


async def on_join(event: JoinedEvent) -> None:
    await event.chat.send_message(
        room=event.room_name, text=f"Hi, my name is {event.user_name}, I'm here to help. :)"
    )


async def on_message(message: ChatMessage) -> None:
    if not LISTEN.is_set():
        LOG.warning("Clippy is not enabled right now!")
        return
    elif user_is_ignored(message.user):
        LOG.warning("User %s requested to be ignored! Skipping!", message.user.display_name)
        return
    elif message.text.startswith("!"):
        return

    message_words = message.text.split(" ")
    misspelled = SPELLCHECKER.unknown(message_words)
    misspelled_cnt = len(misspelled)
    LOG.info(
        "Found %s potential errors in message from %s: %s",
        misspelled_cnt,
        message.user.display_name,
        message.text,
    )

    if misspelled_cnt > 0:
        corrections = ", ".join(
            list(map(lambda x: f'"{x}" (did you mean "{SPELLCHECKER.correction(x)}"?)', misspelled))
        )
        await message.reply(
            f"Uh-oh, looks like you misspelled {corrections} Would you like help with that?"
        )


async def on_clippy(cmd: ChatCommand) -> None:
    parts = cmd.text.split(" ")
    argc = len(parts) - 1
    argv = parts[1:]
    LOG.info("Got clippy command with %s args: %s", argc, argv)

    if argc == 0:
        await cmd.reply(
            "I am a bot! Any actions taken by me are automatic! If you would like for me to ignore you, use `!ignoreme`"
        )
    elif argc == 1:
        arg = argv[0].lower()
        if arg == "start":
            msg = "Clippy will start being anoying now! OpieOP"
            LOG.info(msg)
            await cmd.reply(msg)
            LISTEN.set()
        elif arg == "stop":
            msg = "Clippy will stop being anoying... for now... monkaS"
            LOG.info(msg)
            await cmd.reply(msg)
            LISTEN.clear()


async def on_ignore(cmd: ChatCommand) -> None:
    LOG.info("Got ignore request for user: %s", cmd.user.display_name)
    IGNORE_USERS_LCK.acquire()
    IGNORE_USERS.append(cmd.user.id)
    IGNORE_USERS_LCK.release()
    await cmd.reply("Ok! I won't bother you anymore! :)")


async def on_ignore_list(cmd: ChatCommand) -> None:
    users_list = ", ".join(list(map(lambda x: x, IGNORE_USERS)))
    await cmd.reply(f"Ignored users: {users_list}")


async def on_listen(cmd: ChatCommand) -> None:
    LOG.info("Got unignore request for user: %s", cmd.user.display_name)
    IGNORE_USERS_LCK.acquire()
    IGNORE_USERS.remove(cmd.user.id)
    IGNORE_USERS_LCK.release()
    await cmd.reply("Ok! I'll be sure to suggest corrections for you again! :)")


async def main():
    global IGNORE_USERS

    # Parse CMD Line Args
    args = parse_args()

    # Configure App
    log_level = ERROR if (args.log_level is None) else args.log_level
    debug = log_level == NOTSET
    basicConfig(level=log_level)

    # Setup Twitch Auth Flow
    twitch = await Twitch(__app_id__, __app_secret__)
    twitch.get_users()
    auth = UserAuthenticator(twitch=twitch, scopes=API_SCOPES, force_verify=False)
    access, refresh = await auth.authenticate()
    await twitch.set_user_authentication(
        token=access, scope=API_SCOPES, refresh_token=refresh, validate=False
    )

    # Load ignored users cfg
    IGNORE_USERS_LCK.acquire()
    IGNORE_USERS = load_ignore_users(args.ignore_users)
    IGNORE_USERS_LCK.release()

    # Setup Chat Bot
    chat = await Chat(twitch=twitch, initial_channel=[args.twitch_channel])
    chat.register_event(ChatEvent.JOINED, on_join)
    chat.register_event(ChatEvent.MESSAGE, on_message)
    chat.set_prefix("!")
    chat.register_command("clippy", on_clippy)
    chat.register_command("ignore", on_ignore)
    chat.register_command("ignorelist", on_ignore_list)
    chat.register_command("listen", on_listen)

    # Start the Chat Bot
    LOG.info("Starting twitch bot...")
    LISTEN.set()
    chat.start()

    # Wait for exit signal and gracefully close
    try:
        input("Press any key to stop!\n")
    except KeyboardInterrupt as e:
        LOG.warning("Recieved Ctrl+C input!")
    finally:
        IGNORE_USERS_LCK.acquire()
        save_ignore_users(args.ignore_users, IGNORE_USERS)
        IGNORE_USERS_LCK.release()

        chat.stop()
        await twitch.close()


if __name__ == "__main__":
    run(main())
