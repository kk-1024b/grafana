#!/bin/bash

#case 1:
# GF_XXX is for docker import
# if using docker pull, there is no GF_XXX

sudo docker import grafana dt_dashboards:1.0

sudo docker run -d --restart=always \
    --name dt_dashboards \
	-p 9696:3000 \
	-e GF_PATHS_HOME=/usr/share/grafana \
	-e GF_PATHS_PROVISIONING=/etc/grafana/provisioning \
	-e GF_SECURITY_ADMIN_PASSWORD=admin \
	-e GF_PATHS_DATA=/var/lib/grafana \
	-e GF_PATHS_LOGS=/var/log/grafana \
	-e PATH=/usr/share/grafana/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
	-e GF_PATHS_PLUGINS=/var/lib/grafana/plugins \
	-e GF_PATHS_CONFIG=/etc/grafana/grafana.ini \
	dt_dashboards:1.0 \
    sh -c "/run.sh"


# case 2:
# docker pull grafana/grafana

# # docker run, and save data to ~/grafana-data
# docker run -d --name grafana \
#   -p 3000:3000 \
#   -v $HOME/grafana-data:/var/lib/grafana \
#   -e GF_SECURITY_ADMIN_PASSWORD=admin \
#   grafana/grafana
