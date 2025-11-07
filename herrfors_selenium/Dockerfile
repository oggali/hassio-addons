ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

# Install OS packages
RUN apt-get update && apt-get install -y \
    wget \
    ca-certificates \
    unzip \
    python3 \
    python3-pip \
    chromium \
    chromium-driver \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip3 install --no-cache-dir selenium webdriver-manager requests cryptography pytz

# Copy addon files
WORKDIR /app
COPY run.sh /run.sh
COPY fetch_and_save.py /app/fetch_and_save.py
COPY herrfors_session.py /app/herrfors_session.py
COPY decode_token.py /app/decode_token.py
RUN chmod +x /run.sh

CMD [ "/run.sh" ]

