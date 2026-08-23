FROM ghcr.io/hassio-addons/base:15.0.5

RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-setuptools \
    py3-wheel

COPY app /app
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
