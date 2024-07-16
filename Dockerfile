FROM python:3.9-alpine

ARG CLIPPYBOT_SECRET

ARG TWITCH_CHANNEL
ENV TWITCH_CHANNEL ""

ARG APP_DIR
ENV APP_DIR "/opt/clippybot"

ARG DATA_DIR
ENV DATA_DIR "/srv/clippybot"

RUN mkdir -p ${APP_DIR} -m 755
RUN mkdir -p ${DATA_DIR} -m 755

COPY . ${APP_DIR}
RUN pip install --upgrade pip
WORKDIR ${APP_DIR}
RUN pip install -e .

WORKDIR ${DATA_DIR}

ENTRYPOINT clippybot --twitch-channel $TWITCH_CHANNEL