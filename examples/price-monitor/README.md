# price-monitor

Get told when a product's price or stock changes.

## Stores that publish product data (most do)

Shopify stores and any page with schema.org JSON-LD or OpenGraph product tags need no
selectors: `unlimited web` finds the product data and emits one `product` event per variant.

```bash
unlimited inspect https://www.allbirds.com/products/mens-strider-explore
unlimited web https://www.allbirds.com/products/mens-strider-explore | unlimited diff
```

The first run saves a baseline. Later runs print only what changed:

```text
CHANGE DETECTED  Men's Strider Explore - Natural Black (Dark Grey Sole) - 9
  price  130.0 → 110.0
  availability  OutOfStock → InStock
```

## Any other page: point at the elements

```bash
unlimited run examples/price-monitor/pipeline.yml
```

The pipeline extracts title, price and stock with CSS selectors, converts the price to a
number, and diffs it against the previous run. Changes go to `price-changes.xml`.

Be polite: check a product a few times a day, not every minute.
