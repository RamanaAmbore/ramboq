# GitHub webhook receiver. Proxies to the local `webhook` (adnanh) listener on port 9001.
# Route: POST https://webhook.ramboq.com/hooks/ramboq-deploy

server {
    server_name webhook.ramboq.com;

    location / {
        proxy_pass http://127.0.0.1:9001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/webhook.ramboq.com/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/webhook.ramboq.com/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot
}

server {
    if ($host = webhook.ramboq.com) {
        return 301 https://$host$request_uri;
    } # managed by Certbot

    listen 80;
    server_name webhook.ramboq.com;
    return 404;
}
