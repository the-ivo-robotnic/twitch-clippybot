"""Application Entry Point"""

from argparse import ArgumentParser, Namespace
from asyncio import get_running_loop, run
from functools import partial
from json import dump, load
from logging import ERROR, INFO, NOTSET, basicConfig, getLogger
from threading import Event, Lock
from typing import Callable, List
from urllib.parse import urlparse, ParseResult


from decorator import decorator
from spellchecker import SpellChecker
from twitchAPI.chat import Chat, ChatCommand, ChatMessage, ChatUser, JoinedEvent
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.twitch import Twitch
from twitchAPI.helper import first
from twitchAPI.type import AuthScope, ChatEvent
from twitchAPI.eventsub.websocket import EventSubWebsocket
from twitchAPI.object.api import CustomReward
from twitchAPI.type import TwitchAPIException
from twitchAPI.object.eventsub import (
    ChannelPointsCustomRewardRedemptionAddEvent,
    ChannelPointsCustomRewardRedemptionData,
)

from . import __metadata__, __twitch_app_id__, __twitch_app_secret__

LOG = getLogger(__name__)
API_SCOPES = [
    AuthScope.CHAT_READ,
    AuthScope.CHAT_EDIT,
    AuthScope.USER_BOT,
    AuthScope.CHANNEL_MANAGE_REDEMPTIONS,
]
SPELLCHECKER = SpellChecker()
IGNORE_USERS = []
IGNORE_USERS_LCK = Lock()
BOT_ENABLE = Event()


def load_ignore_users(cfg_path: str) -> List[str]:
    """
    Load the list of ignored users from.

    :param cfg_path: Path to config file.
    :type cfg_path: str
    :return: list of user id's to ignore
    :rtype: List[str]
    """
    try:
        with open(cfg_path, "r", encoding="utf-8") as file:
            data = load(file)
            ignored_users = data.get("ignore-users")
            return [] if ignored_users is None else ignored_users
    except FileNotFoundError:
        LOG.warning("No config found: %s", cfg_path)
        return []


def save_ignore_users(cfg_path: str, ignore_users: List[str] = []) -> None:
    """
    Save the list of ignored users to file.

    :param cfg_path: Path to config file.
    :type cfg_path: str
    :param ignore_users: list of user id's to ignore, defaults to []
    :type ignore_users: List[str], optional
    """
    with open(cfg_path, "w+", encoding="utf-8") as file:
        data = {"ignore-users": ignore_users}
        dump(data, file)


def parse_args() -> Namespace:
    """
    Parse the command line args

    :return: Resolved command line arguments
    :rtype: Namespace
    """
    parser = ArgumentParser(
        prog=__metadata__.get("name"), description=__metadata__.get("description")
    )
    parser.add_argument(
        "--version",
        action="version",
        version=__metadata__.get("version"),
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


@decorator
async def bot_enabled(func: Callable, event: any, *args, **kwargs) -> any:
    """
    Decorator to check for bot-enabled status on handlers

    :param func: Decorated handler to call
    :type func: Callable
    :param event: Event payload from the handler
    :type event: any
    :raises RuntimeError: _description_
    :return: The return value of the handler function
    :rtype: any
    """
    if not BOT_ENABLE.is_set():
        raise RuntimeError(f"Cannot run {func} because bot is disabled!")
    return await func(event, *args, **kwargs)


@decorator
async def user_is_mod(func: Callable, event: any, *args, **kwargs) -> any:
    """
    Decorator to check for user-mod status status on handlers

    :param func: Decorated handler to call
    :type func: Callable
    :param event: Event payload from the handler
    :type event: any
    :raises RuntimeError: _description_
    :return: The return value of the handler function
    :rtype: any
    """
    if not hasattr(event, "user") or not isinstance(event.user, ChatUser):
        raise ValueError(
            f"Cannot use @user_is_mod on {func} because event type"
            f" {type(event)} does not have a ChatUser payload!"
        )
    user: ChatUser = event.user
    if (
        (user.badges is not None) and (user.badges.get("broadcaster") is not None)
    ) or user.mod:
        return await func(event, *args, **kwargs)
    await event.reply("You must be a mod to use that command!")
    raise RuntimeError(
        f"Cannot run {func} because ChatUser {user.display_name} is not a mod!"
    )


@decorator
async def user_not_ignored(func: Callable, event: any, *args, **kwargs) -> any:
    """
    Decorator to check for user-ignored status on handlers

    :param func: Decorated handler to call
    :type func: Callable
    :param event: Event payload from the handler
    :type event: any
    :raises RuntimeError: _description_
    :return: The return value of the handler function
    :rtype: any
    """
    if not hasattr(event, "user") or not isinstance(event.user, ChatUser):
        raise ValueError(
            f"Cannot use @user_not_ignored on {func} because event type"
            f" {type(event)} does not have a ChatUser payload!"
        )
    user: ChatUser = event.user
    if user.id in IGNORE_USERS:
        raise RuntimeError(
            f"Cannot run {func} because ChatUser {user.display_name}"
            " requested to be ignored!"
        )

    return await func(event, *args, **kwargs)


@decorator
async def not_command(func: Callable, message: ChatMessage, *args, **kwargs) -> any:
    """
    Decorator to check for command in message on handlers

    :param func: Decorated handler to call
    :type func: Callable
    :param event: Event payload from the handler
    :type event: any
    :raises RuntimeError: _description_
    :return: The return value of the handler function
    :rtype: any
    """
    if not isinstance(message, ChatMessage):
        raise ValueError(
            f"Cannot use @not_command on {func} because event type {type(message)}"
            " is not a ChatMessage payload!"
        )
    if message.text.startswith("!"):
        LOG.warning(
            "Skipping %s because %s appears to be a command!", func, message.text
        )
        return
    return await func(message, *args, **kwargs)


async def on_join(event: JoinedEvent) -> None:
    """
    Handle Twitch joined event.
    :param event: Joined event payload
    :type event: JoinedEvent
    """
    await event.chat.send_message(
        room=event.room_name,
        text=f"📎 Hi, my name is {event.user_name}, I'm here to help. :) 📎",
    )


def on_point_redeem(event: ChannelPointsCustomRewardRedemptionAddEvent) -> None:
    """
    Handle Twitch channel point redeem.

    :param event: _description_
    :type event: ChannelPointsCustomRewardRedemptionAddEvent
    """
    data: ChannelPointsCustomRewardRedemptionData = event.event
    LOG.info(data.to_dict())


@bot_enabled
@not_command
@user_not_ignored
async def on_message(message: ChatMessage) -> None:
    """
    Handle twitch messages

    :param message: Twitch chat message payload
    :type message: ChatMessage
    """
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
        corrections = []
        for word in misspelled:
            correction = SPELLCHECKER.correction(word)
            if(correction is None):
                continue
            corrections.append(f'{word} (did you mean "{correction}"?)')
        corrections = ", ".join(corrections)
        if len(corrections) == 0:
            return
        await message.reply(
            f"📎 Uh-oh, looks like you misspelled {corrections}"
            " Would you like help with that? 📎"
        )


@bot_enabled
async def on_about(cmd: ChatCommand) -> None:
    """
    Handle about command

    :param cmd: Twitch chat command payload
    :type cmd: ChatCommand
    """
    await cmd.reply(
        "📎 I am a bot! I am here to autocorrect everything you say."
        "Isn't that helpful? 📎"
    )


@user_is_mod
async def on_enable(cmd: ChatCommand) -> None:
    """
    Handle enable command

    :param cmd: Twitch chat command payload
    :type cmd: ChatCommand
    """
    msg = "📎 Clippy will start being anoying now! OpieOP 📎"
    LOG.info(msg)
    await cmd.reply(msg)
    BOT_ENABLE.set()


@user_is_mod
async def on_disable(cmd: ChatCommand) -> None:
    """
    Handle disable command

    :param cmd: Twitch chat command payload
    :type cmd: ChatCommand
    """
    msg = "📎 Clippy will stop being anoying... for now... monkaS 📎"
    LOG.info(msg)
    await cmd.reply(msg)
    BOT_ENABLE.clear()


@bot_enabled
@user_is_mod
async def on_list(cmd: ChatCommand, twitch: Twitch) -> None:
    """
    Handle list command

    :param cmd: Twitch chat command payload
    :type cmd: ChatCommand
    """
    IGNORE_USERS_LCK.acquire()
    users_from_ids = [i async for i in twitch.get_users(IGNORE_USERS)]
    IGNORE_USERS_LCK.release()
    msg_part = ", ".join(list(map(lambda x: x.display_name, users_from_ids)))
    await cmd.reply(f"Ignored users: {msg_part}")


@bot_enabled
async def on_ignore(cmd: ChatCommand) -> None:
    """
    Handle ignore command

    :param cmd: Twitch chat command payload
    :type cmd: ChatCommand
    """
    LOG.info("Got ignore request for user: %s", cmd.user.display_name)
    IGNORE_USERS_LCK.acquire()
    IGNORE_USERS.append(cmd.user.id)
    IGNORE_USERS_LCK.release()
    await cmd.reply("📎 Ok! I won't bother you anymore! :) 📎")


@bot_enabled
async def on_listen(cmd: ChatCommand) -> None:
    """
    Handle listen command

    :param cmd: Twitch chat command payload
    :type cmd: ChatCommand
    """
    LOG.info("Got unignore request for user: %s", cmd.user.display_name)
    IGNORE_USERS_LCK.acquire()
    IGNORE_USERS.remove(cmd.user.id)
    IGNORE_USERS_LCK.release()
    await cmd.reply("📎 Ok! I'll be sure to suggest corrections for you again! :) 📎")


async def amain():
    """Application async entrypoint"""
    global IGNORE_USERS

    # Parse CMD Line Args
    args = parse_args()

    # Configure App
    log_level = ERROR if (args.log_level is None) else args.log_level
    basicConfig(level=log_level)
    getLogger("asyncio").setLevel(INFO)
    getLogger("twitchAPI").setLevel(INFO)

    # Setup Twitch Auth Flow
    twitch = await Twitch(__twitch_app_id__, __twitch_app_secret__)
    auth = UserAuthenticator(twitch=twitch, scopes=API_SCOPES, force_verify=False)

    auth_url = auth.return_auth_url()
    print(
        f"Open this link in a browser to continue Twitch OAuth Flow:\n\t{auth_url}",
    )
    res_url = input("Paste the resulting link from your browser> ")
    res: ParseResult = urlparse(res_url)
    auth_args = res.query.split("&")
    auth_args = dict(map(lambda x: x.split("="), auth_args))

    access, refresh = await auth.authenticate(user_token=auth_args["code"])
    await twitch.set_user_authentication(
        token=access, scope=API_SCOPES, refresh_token=refresh, validate=False
    )

    # Get the broadcaster payload
    broadcaster = await first(twitch.get_users(logins=[args.twitch_channel]))

    # Create the point redemption
    try:
        reward: CustomReward = await twitch.create_custom_reward(
            broadcaster_id=broadcaster.id,
            title="Enable Clippy",
            cost=69,
            prompt="Enable Clippy the AutoCorrect bot.",
            is_enabled=True,
        )
        rewards: List[CustomReward] = [
            r async for r in twitch.get_custom_reward(broadcaster.id)
        ]
        rewards = list(filter(lambda x: "clippy" in x.title.lower(), rewards))
        if len(rewards) == 0:
            raise TwitchAPIException(
                "No rewards for Clippy were found on"
                f" {broadcaster.display_name}'s channel!"
            )

        # Setup Channel Point EventSub
        eventsub = EventSubWebsocket(twitch=twitch)
        await eventsub.listen_channel_points_custom_reward_redemption_add(
            broadcaster.id, on_point_redeem, reward_id=reward.id
        )
    except TwitchAPIException as e:
        LOG.error("Failed to create channel point reward with reason: %s", e)

    # Load ignored users cfg
    IGNORE_USERS_LCK.acquire()
    IGNORE_USERS = load_ignore_users(args.ignore_users)
    IGNORE_USERS_LCK.release()

    # Setup Chat Bot
    chat = await Chat(twitch=twitch, initial_channel=[args.twitch_channel])
    chat.register_event(ChatEvent.JOINED, on_join)
    chat.register_event(ChatEvent.MESSAGE, on_message)
    chat.set_prefix("!c ")
    chat.register_command("about", on_about)

    chat.register_command("list", partial(on_list, twitch=twitch))
    chat.register_command("ignore", on_ignore)
    chat.register_command("listen", on_listen)

    chat.register_command("enable", on_enable)
    chat.register_command("disable", on_disable)

    # Wait for exit signal and gracefully close
    try:
        # Start the Chat Bot
        LOG.info("Joined Twitch chat -> https://twitch.tv/%s", args.twitch_channel)
        BOT_ENABLE.set()
        chat.start()
        while True:
            pass
    finally:
        IGNORE_USERS_LCK.acquire()
        save_ignore_users(args.ignore_users, IGNORE_USERS)
        IGNORE_USERS_LCK.release()

        chat.stop()
        await twitch.close()
        get_running_loop().close()


def main():
    """Application entrypoint"""
    run(amain())


if __name__ == "__main__":
    main()
