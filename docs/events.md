# Events

Every stage of a pipeline exchanges **events**. Between processes an event is one line of
JSON (JSONL). The format is versioned by its `schema` field and is stable within a major
version: fields may be added, never removed or renamed.

```json
{
  "schema": "unlimitedpipe.event/1",
  "id": "a221e3671f7ed8a73149",
  "source": "web",
  "type": "product",
  "key": "https://store.example/products/shoe#TS-1-9",
  "source_url": "https://store.example/products/shoe",
  "timestamp": null,
  "observed_at": "2026-09-23T12:00:02Z",
  "data": {"name": "Trail Shoe - Size 9", "price": 89.0, "currency": "USD", "availability": "InStock"},
  "metadata": {"method": "json-ld", "status": 200, "final_url": "https://store.example/products/shoe", "elapsed_ms": 212, "not_modified": false},
  "provenance": [
    {"step": "web", "version": "0.1.0"},
    {"step": "filter", "version": "0.1.0", "args": {"expr": "price < 100"}}
  ]
}
```

| Field | Meaning |
| --- | --- |
| `schema` | Format version. Readers reject major versions they do not know. |
| `id` | Identifies this observation: a hash of source, key and data. Same content, same id. |
| `source` | The component that produced the event (`web`, `rss`, a plugin name). |
| `type` | What the event describes: `document`, `product`, `entry`, `element`, `record`, `link`, `change`, `inspection`, `error`. |
| `key` | Stable identity of the thing observed, used by `diff` and `dedupe`. |
| `source_url` | The URL (or `file://` path) that was fetched. |
| `timestamp` | When the thing happened (published, modified), if known. |
| `observed_at` | When UnlimitedPipe saw it (UTC). |
| `data` | The payload. Operators work on it. |
| `metadata` | How it was fetched: `method` (`html`, `json-ld`, `shopify`, `opengraph`, `css`, `rss20`, `atom10`, `json-feed`...), HTTP `status`, `final_url`, `elapsed_ms`, `not_modified`. |
| `provenance` | Every step the event passed through, with the arguments of each operator. |

## Plain JSON is welcome

Objects without the `schema` marker are wrapped as `record` events whose `data` is the object,
so output from `jq`, APIs or other tools can be piped straight in:

```bash
curl -s https://api.example.com/items | jq -c '.items[]' | unlimited filter 'price > 10'
```

`unlimited jsonl --data` and `unlimited json` write plain data back out.

## Field paths

Operators address fields with dotted paths: `title`, `offers.0.price`, `feed.title`. A path is
looked up in `data` first, then in the envelope, so `source_url` and `metadata.status` work
too. `data.x` forces the data lookup.

## Change events

`diff` emits `change` events:

```json
{
  "type": "change",
  "key": "https://acme.example/pricing#Pro",
  "data": {
    "change": "modified",
    "label": "Pro",
    "item_type": "record",
    "summary": "price: $49 → $59",
    "fields": [{"path": "price", "old": "$49", "new": "$59"}],
    "after": {"name": "Pro", "price": "$59"}
  }
}
```

`change` is `added`, `removed` or `modified`. Added and modified changes carry `after`,
removed changes carry `before`. Provenance and `source_url` are kept from the original event.

## Events in feeds

`unlimited feed out.json` writes a [JSON Feed 1.1](https://jsonfeed.org/version/1.1) whose items
carry the complete event under the `_unlimitedpipe` extension:

```json
{"id": "a221e3671f7ed8a73149", "title": "Pro: price: $49 → $59", "url": "https://acme.example/pricing",
 "_unlimitedpipe": {"event": {"schema": "unlimitedpipe.event/1", "...": "..."}}}
```

Reading that feed with `unlimited rss` returns the original events with their provenance and
adds `metadata.via_feed`. One pipeline's output becomes another's source without losing where
the data came from.
