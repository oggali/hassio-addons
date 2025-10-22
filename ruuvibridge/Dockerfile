ARG BUILD_FROM=ghcr.io/hassio-addons/base:15.0.5
FROM $BUILD_FROM

RUN apk add --no-cache ca-certificates wget tar

ENV RUUVI_VERSION=1.6.1

ARG BUILD_ARCH
RUN case "${BUILD_ARCH}" in \
    "aarch64") ARCH="arm64";; \
    "armv7") ARCH="armv7";; \
    *) ARCH="amd64";; \
    esac && \
    wget -O - https://github.com/Scrin/RuuviBridge/releases/download/v${RUUVI_VERSION}/RuuviBridge_linux_${ARCH}.tar.gz \
    | tar xz -C /usr/local/bin && chmod +x /usr/local/bin/RuuviBridge

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
