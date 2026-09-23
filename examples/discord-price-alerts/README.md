# discord-price-alerts

Get a Discord message when a product's price or stock changes.

1. In Discord: Server Settings → Integrations → Webhooks → New Webhook → Copy Webhook URL.
2. Keep the URL secret (anyone with it can post to the channel):

   ```bash
   export DISCORD_WEBHOOK=https://discord.com/api/webhooks/...
   ```

3. Check once an hour:

   ```bash
   unlimited watch --every 1h examples/discord-price-alerts/pipeline.yml
   ```

A message looks like:

```text
Men's Strider Explore - Natural Black (Dark Grey Sole) - 9: price: 130.0 → 110.0
https://www.allbirds.com/products/mens-strider-explore?variant=41334293954640
```

Slack works the same way with a Slack incoming-webhook URL. To run it without a computer on,
`unlimited publish examples/discord-price-alerts/pipeline.yml` sets up a GitHub Actions
workflow; store the URL with `gh secret set DISCORD_WEBHOOK`.

The webhook URL never appears in messages or logs, mentions are disabled, and at most 20
messages go out per run.
