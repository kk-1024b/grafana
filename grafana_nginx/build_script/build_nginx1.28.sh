#!/bin/bash
# /opt/catch2_data is for PUT
# /usr/share/nginx/html/data is for GET
# curl -u user:pass123 -T /home/kk/catch2_data/pywatcher/data/testResult.csv http://localhost:9699/details/sources/XXX/testResult.csv

docker run --restart=always -d --name test_nginx1.28 \
	-p 9699:8080 \
	-v /home/kk/catch2_data/data:/opt/catch2_data \
	-v /home/kk/catch2_data/data:/usr/share/nginx/html/data \
	-e BASIC_USER=user \
	-e BASIC_PASS=pass123 \
	-e UPLOAD=true \
	nginx:1.28 \
	sh -c "/docker-entrypoint.sh nginx -g 'daemon off;'"  # it's necessary for docker import
