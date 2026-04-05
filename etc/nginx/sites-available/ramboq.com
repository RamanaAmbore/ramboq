# Proxies to uvicorn on port 8000. Uvicorn serves the Litestar REST/WS API
# and the SvelteKit SPA build as static files.

server {
    server_name ramboq.com www.ramboq.com;

    # ── Litestar API + WebSocket ───────────────────────────────────────────
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }

    location /docs {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }

    # ── SvelteKit SPA (served by Litestar static files handler) ───────────
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # ── Webhook listener ───────────────────────────────────────────────────
    location /hooks/update {
        proxy_pass http://127.0.0.1:9001/hooks/ramboq-deploy;
        proxy_http_version 1.1;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Host $host;
        proxy_set_header X-Hub-Signature-256 $http_x_hub_signature_256;
    }

    location /hooks/log {
        proxy_pass http://127.0.0.1:9001/hooks/log-incoming;
        proxy_http_version 1.1;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Host $host;
    }

    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/ramboq.com/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/ramboq.com/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot
}

server {
    if ($host = www.ramboq.com) {
        return 301 https://$host$request_uri;
    } # managed by Certbot

    if ($host = ramboq.com) {
        return 301 https://$host$request_uri;
    } # managed by Certbot

    listen 80;
    server_name ramboq.com www.ramboq.com;
    return 404; # managed by Certbot
}
