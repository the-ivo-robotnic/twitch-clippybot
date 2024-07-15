FROM python:3.9-alpine

ARG OMT_APP_SECRET

ARG OMT_HOST
ENV OMT_HOST 0.0.0.0

ARG OMT_PORT
ENV OMT_PORT 7064

ARG OMT_DATA_DIR
ENV OMT_DATA_DIR "/srv/omt"

RUN mkdir -p ${OMT_DATA_DIR} -m 755
COPY ${WHL_PATH} ${WHL_PATH}

RUN find . -iname '*.whl' -exec pip install {} \;
RUN find . -iname '*.whl' -exec rm {} \;

WORKDIR ${OMT_DATA_DIR}
ENTRYPOINT obs-media-triggers --host $OMT_HOST --port $OMT_PORT -vv