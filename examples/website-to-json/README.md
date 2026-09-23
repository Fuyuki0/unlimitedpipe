# website-to-json

Turn any page into clean JSON.

```bash
unlimited web https://example.com | unlimited select title url | unlimited json
```

```json
[
  {
    "title": "Example Domain",
    "url": "https://example.com"
  }
]
```

As a pipeline, writing `example.json` next to the pipeline file:

```bash
unlimited run examples/website-to-json/pipeline.yml
```

Try `--links` or `--tables` on `unlimited web` to include a page's links and tables, and
`unlimited inspect URL` to see what else a page offers.
