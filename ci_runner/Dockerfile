FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Shanghai \
    LANG=C.UTF-8 \
    CCACHE_DIR=/cache/ccache \
    PATH=/usr/lib/ccache:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential gcc g++ make cmake ninja-build ccache \
      python3 python3-pip python3-venv \
      git openssh-client ca-certificates \
      tzdata \
      vim sqlite3 curl less procps \
    && ln -fs /usr/share/zoneinfo/$TZ /etc/localtime \
    && dpkg-reconfigure -f noninteractive tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY config/ ./config/

ARG GITLAB_HOST=gitlab.internal
RUN mkdir -p /root/.ssh && chmod 700 /root/.ssh \
    && ssh-keyscan -H "$GITLAB_HOST" >> /root/.ssh/known_hosts 2>/dev/null || true

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]