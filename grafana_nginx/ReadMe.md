## 1: add grafana_nginx for dashboards

### 1.1 install script
The install script is in **/build_script/**, and some dependencies file is in **/app** which is python script;

### 1.1 install grafana
#### 1.1.1 details see **/build_script/build_grafana.sh**, 

```
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
```

some **ENV** is for **docker import + docker run**, if you use **docker pull + docker run**, it's not necessary;
```
	-e GF_PATHS_HOME=/usr/share/grafana \
	-e GF_PATHS_PROVISIONING=/etc/grafana/provisioning \
	-e GF_SECURITY_ADMIN_PASSWORD=admin \
	-e GF_PATHS_DATA=/var/lib/grafana \
	-e GF_PATHS_LOGS=/var/log/grafana \
	-e PATH=/usr/share/grafana/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
	-e GF_PATHS_PLUGINS=/var/lib/grafana/plugins \
	-e GF_PATHS_CONFIG=/etc/grafana/grafana.ini \
```



#### 1.1.2 grafana plugins
**infinity** is necessary for **CSV/JSON data format**. In VDI you need install **infinity offline**, please reference to **离线安装 infinity**.

```
//# GitHub release
// 3.3.0 已支持 Grafana 12.x，无需再开 Angular
wget https://github.com/yesoreyeram/grafana-infinity-datasource/releases/download/v3.3.0/yesoreyeram-infinity-datasource-3.3.0.zip


//move zip to server
scp yesoreyeram-infinity-datasource-3.3.0.zip user@offline:/tmp/


//
sudo unzip -q /tmp/yesoreyeram-infinity-datasource-3.3.0.zip -d /var/lib/grafana/plugins

sudo chown -R grafana:grafana /var/lib/grafana/plugins

//restart grafana
//for docker
docker restart grafana-server   

//for ubuntu
sudo systemctl restart grafana-server
```

### 1.2 install nginx
nginx is a static file server that support **GET** and **PUT**，so CI/CD can **put** files to nginx server, and grafana can **get** result.csv from nginx server;

#### 1.2.1 nginx config
```
vim /etc/nginx/conf.d.default.conf

// insert
location /details/ {
	root /opt/download;
	dav_methods PUT DELETE MKCOL COPY MOVE; //dav
	dav_access user:rw group:rw all:r;

	create_full_put_path on;
}

```

#### 1.2.2 update config
```
nginx -t
nginx -s reload

```


### 1.3 install python
python is a directory watcher that watch the change of dir;

**note**:

 1: python script is in **/app** 

 2: python share **/data** with nginx 
```

mkdir -p /data/details/sources  //store catch2 results, and python watcher the change
mkdir -p /data/details/html     //store html file
```

 3: python don't support delete records of catcht2 result;
 4: catch2 result format referenct to **/test_data/testResult.csv**, and the grafana csv format reference to **/test_data/catch2Result.csv**.