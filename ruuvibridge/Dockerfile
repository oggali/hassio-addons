ARG BUILD_FROM=ghcr.io/hassio-addons/base-debian:15.0.5
FROM $BUILD_FROM

RUN apk add --no-cache ca-certificates wget tar

# Remove or comment this line
ENV RUUVI_VERSION=1.0.0

ARG BUILD_ARCH
ARG RUUVI_VERSION
RUN case "${BUILD_ARCH}" in \
    "aarch64") ARCH="arm64";; \
    "armv7") ARCH="armv7";; \
    "amd64"|"x86_64") ARCH="amd64";; \
    *) echo "Unsupported BUILD_ARCH: ${BUILD_ARCH}" && exit 1;; \
    esac && \
    wget -O - https://github.com/Scrin/RuuviBridge/releases/download/v${RUUVI_VERSION}/ruuvibridge-v${RUUVI_VERSION}-linux-${ARCH}.tar.gz \
    | tar xz -C /usr/local/bin && chmod +x /usr/local/bin/ruuvibridge

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
