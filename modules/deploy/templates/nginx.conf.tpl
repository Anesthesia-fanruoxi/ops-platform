# ============================================================
# Nginx 配置文件模板
# 用于生成标准 Nginx 反向代理 + 静态文件服务配置
#
# 占位符说明:
#   {{server_name}}       - 域名，如 bjjfapi.hzbxhd.com
#   {{ssl_cert}}          - SSL证书路径，如 /etc/nginx/cert/hzbxhd.com.pem
#   {{ssl_key}}           - SSL密钥路径，如 /etc/nginx/cert/hzbxhd.com.key
#   {{web_root}}          - 前端静态文件目录，如 /www/bjjf/api/web
#   {{upload_alias}}      - 上传文件目录，如 /www/bjjf/api/upload/public
#   {{html_alias}}        - HTML模板目录，如 /www/bjjf/api/html
#   {{k8s_cluster_ip}}    - K8s集群内网地址，如 172.16.0.10
#   {{gateway_nodeport}}  - Gateway服务 NodePort，如 41837
#   {{h5_alias}}          - H5页面目录（可选），如 /www/bjjf/api/h5
#   {{client_max_body}}   - 最大上传大小（可选），如 20m
# ============================================================

# ─── HTTP (80) ──────────────────────────────────────────────
server {
    listen 80;
    server_name {{server_name}};

    location /ystg {
        alias {{upload_alias}};
    }
    location /html {
        alias {{html_alias}};
    }
    location /h5 {
        alias {{h5_alias}};
    }
    location /prod-api/ {
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $proxy_protocol_addr;
        proxy_set_header REMOTE-HOST $proxy_protocol_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_pass http://{{k8s_cluster_ip}}:{{gateway_nodeport}}/;
    }
    location / {
        root {{web_root}};
        try_files $uri $uri/ /index.html;
        index index.html index.htm;
    }
    location /.well-known/acme-challenge/ {
        root /opt/ssl/;
    }
    error_page 500 502 503 504 /50x.html;
    location = /50x.html {
        root html;
    }
}

# ─── HTTPS (443) ────────────────────────────────────────────
server {
    listen 443 ssl proxy_protocol;
    charset utf-8;
    server_name {{server_name}};

    ssl_certificate {{ssl_cert}};
    ssl_certificate_key {{ssl_key}};
    ssl_session_timeout 5m;
    ssl_protocols TLSv1 TLSv1.1 TLSv1.2;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:HIGH:!aNULL:!MD5:!RC4:!DHE;
    ssl_prefer_server_ciphers on;

    location /ystg {
        alias {{upload_alias}};
    }
    location /html {
        alias {{html_alias}};
    }
    location /h5 {
        alias {{h5_alias}};
    }
    location /prod-api/ {
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $proxy_protocol_addr;
        proxy_set_header X-Forwarded-For $proxy_protocol_addr;
        proxy_pass http://{{k8s_cluster_ip}}:{{gateway_nodeport}}/;
    }
    location / {
        root {{web_root}};
        try_files $uri $uri/ /index.html;
        index index.html index.htm;
    }
    location /.well-known/acme-challenge/ {
        root /opt/ssl/;
    }
    error_page 500 502 503 504 /50x.html;
    location = /50x.html {
        root html;
    }
}
