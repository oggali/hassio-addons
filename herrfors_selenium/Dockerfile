FROM ghcr.io/hassio-addons/base:15.0.5

# Install dependencies for Selenium + Chromium
RUN apk add --no-cache \
    bash \
    chromium \
    chromium-chromedriver \
    xvfb \
    unzip \
    wget \
    py3-pip \
    py3-setuptools \
    py3-wheel


#WORKDIR /app
#COPY app /app
#
#
#RUN pip install --no-cache-dir -r app/requirements.txt
#
#RUN chmod +x /app/main.py /app/refresh_server.py /app/decode_encode_token.py /app/herrfors_session.py
#COPY run.sh /run.sh
#RUN chmod +x /run.sh
#
#CMD ["run.sh"]

COPY app /app

RUN pip install --no-cache-dir -r /app/requirements.txt

COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
