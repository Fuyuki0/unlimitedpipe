# competitor-watch

Watch a competitor's pricing or catalog page and get one event per change: a plan added, a
plan removed, a price changed.

```bash
unlimited web https://competitor.example/pricing \
    --each .plan --field name=.plan-name --field price=.price \
  | unlimited diff --key name
```

```text
CHANGE DETECTED  Pro
  price  $49 → $59
  https://competitor.example/pricing
```

`--each` picks the repeating element (one plan, one product), `--field NAME=CSS` picks values
inside it, `NAME=CSS@attr` reads an attribute such as `href`. `diff --key name` matches items
by name, so reordering the page is not reported as a change.

The pipeline file does the same for two category pages of books.toscrape.com (a sandbox made
for scraping practice):

```bash
unlimited run examples/competitor-watch/pipeline.yml
```

Use `unlimited inspect URL` first: if the page publishes JSON-LD products or is a Shopify
store, `unlimited web URL | unlimited diff` works without any selectors.
