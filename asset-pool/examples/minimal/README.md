# Example: minimal

The smallest possible asset pool: `server.js` serves `assets.example.json`
over the [asset-pool contract](../../README.md), nothing else.

```bash
ASSET_POOL_TOKEN=change-me node server.js
node ../../bin/check.js http://127.0.0.1:8095 --token change-me
```

This proves out `collect_assets` end to end — listing, filtering, auth,
schema validation — and is enough for the agent's `app_asset_listele`/
`app_asset_detay` to work against it (point `APP_INTERNAL_URL` at
`http://127.0.0.1:8095` and `APP_INTERNAL_TOKEN` at `change-me`).

## Why `medya_dogrula`/`medya_hazirla` won't succeed against it

`assets.example.json`'s URLs (`https://cdn.example.com/...`) are
placeholders — that host doesn't resolve. That's on purpose: this example
only demonstrates `collect_assets`, not `prepare_media`. The agent's
`medya_dogrula`/`medya_hazirla` do a real SSRF-safe fetch of whatever URL the
pool returns (DNS resolution, public-IP check, HTTPS-only, real byte probe),
so they will correctly fail on these — that's the tool working as designed,
not a bug in your setup. To see them succeed, point `assets.example.json` at
real, publicly reachable `https://` files, or use
[`examples/karatahta`](../karatahta) as a template for a pool backed by real
signed storage URLs.
