FROM debian:bookworm-slim

RUN echo "deb http://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm main contrib non-free non-free-firmware\n\
deb http://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-updates main contrib non-free non-free-firmware\n\
deb http://mirrors.tuna.tsinghua.edu.cn/debian-security/ bookworm-security main contrib non-free non-free-firmware" \
    > /etc/apt/sources.list

RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx-extras \
    supervisor \
    apache2-utils \
    python3 \
    python3-pip \
    sqlite3 \
    vim \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install flask --break-system-packages -i https://pypi.tuna.tsinghua.edu.cn/simple

RUN htpasswd -cb /etc/nginx/.htpasswd user pass123

COPY app_catch2/ /app/
COPY app_web/    /app_web/

COPY conf/nginx.conf        /etc/nginx/sites-available/default
COPY conf/supervisord.conf  /etc/supervisor/conf.d/all.conf

RUN rm -f /etc/nginx/sites-enabled/default \
    && ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default

EXPOSE 3000 8080

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/all.conf"]
