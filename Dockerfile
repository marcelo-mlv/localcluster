FROM apache/spark:4.1.3-python3

USER root

# Pin versions and add retry/timeout flags to survive flaky PyPI connections.
# --retries 5: retry failed downloads up to 5 times
# --timeout 120: wait up to 2 minutes per chunk (default is 15 s)
# --no-cache-dir: keep the image lean (no pip wheel cache stored in the layer)
RUN pip install --no-cache-dir --retries 5 --timeout 120 \
        matplotlib==3.9.4 \
        pandas==2.2.3 \
        pyyaml==6.0.2

RUN mkdir -p /opt/spark/events   && chmod 777 /opt/spark/events   && \
    mkdir -p /opt/spark/outputs  && chmod 777 /opt/spark/outputs  && \
    mkdir -p /opt/spark/inputs   && chmod 777 /opt/spark/inputs   && \
    mkdir -p /opt/spark/scenarios && chmod 755 /opt/spark/scenarios

ENV MPLCONFIGDIR=/tmp/matplotlib
USER spark

WORKDIR /opt/spark/work-dir
