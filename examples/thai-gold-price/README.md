# Thai gold price

Every price announcement of the Thai Gold Traders Association (สมาคมค้าทองคำ): bar gold buy
and sell, jewelry sell, and the change since the previous announcement. The association
announces several times on busy days; each announcement becomes one item.

```bash
pip install "unlimitedpipe[browser]" && playwright install chromium   # the page needs JavaScript
unlimited run examples/thai-gold-price/pipeline.yml          # the latest announcement
unlimited watch --every 30m examples/thai-gold-price/pipeline.yml   # each new one as it comes
```

The association's terms allow personal, non-commercial use only, so this runs for you and is
not part of the public feed catalog. Do not republish the prices.
