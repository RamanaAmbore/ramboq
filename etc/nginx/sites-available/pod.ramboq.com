server {
    server_name pod.ramboq.com;

    location / {
        proxy_pass http://localhost:8504;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }

    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/ramboq.com/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/ramboq.com/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot
}

server {
    if ($host = pod.ramboq.com) {
        return 301 https://$host$request_uri;
    } # managed by Certbot

    listen 80;
    server_name pod.ramboq.com;
    return 404;
}
