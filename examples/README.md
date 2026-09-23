# Examples

Every example runs as-is with `unlimited run examples/NAME/pipeline.yml`. Outputs are written
next to the pipeline file.

| Example | What it shows |
| --- | --- |
| [website-to-json](website-to-json) | A page as clean JSON |
| [rss-news-pipeline](rss-news-pipeline) | Merge feeds, filter, publish only new items as RSS |
| [github-release-watch](github-release-watch) | New releases of any public repo, no token |
| [price-monitor](price-monitor) | Price and stock changes, with or without selectors |
| [competitor-watch](competitor-watch) | Added, removed and changed items on a listing page |
| [multi-source-research](multi-source-research) | One topic across several sources into a CSV |
| [plugin-hackernews](plugin-hackernews) | A complete connector package to copy |

Change detection keeps its state in your user data directory. Set
`UNLIMITEDPIPE_STATE_DIR=./state` to keep it next to the example instead.
