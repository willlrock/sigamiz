# Cloudflare Tunnel Deployment

Use Cloudflare Tunnel when the server has no static public IP. The server opens an outbound `cloudflared` connection to Cloudflare, and Cloudflare routes the public hostname to local FastAPI.

## 1. Prepare DNS

- Move the domain to Cloudflare or make sure the target subdomain is managed in Cloudflare DNS.
- Pick the public hostname, for example `sigamiz.uz` or `app.sigamiz.uz`.

## 2. Install And Login

On the server:

```bash
cloudflared tunnel login
cloudflared tunnel create sigamiz
```

`cloudflared tunnel create` prints a tunnel ID and creates a credentials JSON file. Put those values into `/etc/cloudflared/config.yml` based on `cloudflared.example.yml`.

Example:

```yaml
tunnel: 00000000-0000-0000-0000-000000000000
credentials-file: /etc/cloudflared/00000000-0000-0000-0000-000000000000.json

ingress:
  - hostname: sigamiz.uz
    service: http://127.0.0.1:8000
  - service: http_status:404
```

## 3. Route DNS

```bash
cloudflared tunnel route dns sigamiz sigamiz.uz
```

For a subdomain:

```bash
cloudflared tunnel route dns sigamiz app.sigamiz.uz
```

## 4. Run As A Service

```bash
sudo cloudflared service install
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared
```

The existing backend service can keep listening on `127.0.0.1:8000`; no public inbound port or static IP is required.

## 5. Environment

Set these in `.env` on production:

```env
SITE_URL=https://sigamiz.uz
BOT_USERNAME=your_bot_username_without_at
SESSION_SECRET=generate_a_long_random_secret
```

Telegram Login Widget requires the production domain to be configured in BotFather for the bot.

## 6. Smoke Test

```bash
curl -I http://127.0.0.1:8000/
curl -I https://sigamiz.uz/
journalctl -u cloudflared -f
```
