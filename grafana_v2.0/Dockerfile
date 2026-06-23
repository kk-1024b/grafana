FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx-extras \
    supervisor \
    apache2-utils \
    python3 \
    curl \
    gnupg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Grafana from official apt repo
RUN curl -fsSL https://apt.grafana.com/gpg.key | gpg --dearmor -o /etc/apt/keyrings/grafana.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" \
       > /etc/apt/sources.list.d/grafana.list \
    && apt-get update && apt-get install -y --no-install-recommends grafana \
    && rm -rf /var/lib/apt/lists/*

# Install Infinity datasource plugin
RUN grafana cli --pluginsDir /var/lib/grafana/plugins plugins install yesoreyeram-infinity-datasource

# Generate nginx Basic Auth (user:pass123)
RUN htpasswd -cb /etc/nginx/.htpasswd user pass123

# Bake in Python watcher scripts
COPY app/ /app/

# nginx and supervisord configs
COPY conf/nginx.conf /etc/nginx/sites-available/default
COPY conf/supervisord.conf /etc/supervisor/conf.d/all.conf

RUN rm -f /etc/nginx/sites-enabled/default \
    && ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default

EXPOSE 3000 8080

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/all.conf"]
