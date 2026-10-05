#!/bin/sh
# Rebuild the Hugging Face dataset unlimitedpipe/feed-history from the catalog's archive and
# mirror it to Kaggle: the build runs on a GitHub machine (workflow "History dataset"), the
# upload runs here, where the Hugging Face login is. Run monthly by a systemd timer
# (unlimitedpipe-feed-history.timer); needs gh and research/.venv (huggingface_hub).
set -eu
repo=Fuyuki0/unlimitedpipe
here="$(cd "$(dirname "$0")/../.." && pwd)"
work="${FEED_HISTORY_WORK:-/srv/unlimitedpipe-history/feed-history-build}"

before="$(gh run list -R "$repo" -w history-data.yml -L 1 --json databaseId -q '.[0].databaseId')"
gh workflow run history-data.yml -R "$repo"
run="$before"
while [ "$run" = "$before" ]; do
  sleep 15
  run="$(gh run list -R "$repo" -w history-data.yml -L 1 --json databaseId -q '.[0].databaseId')"
done
gh run watch "$run" -R "$repo" --exit-status >/dev/null

rm -rf "$work"
gh run download "$run" -R "$repo" -n feed-history -D "$work"
"$here/research/.venv/bin/python" - "$work" <<'PY'
import sys
from huggingface_hub import HfApi

HfApi().upload_folder(
    folder_path=sys.argv[1],
    repo_id="unlimitedpipe/feed-history",
    repo_type="dataset",
    # the feeds' files as built: one gone from the catalog goes from the dataset too
    delete_patterns=["data/*.parquet", "wikipedia/*.parquet"],
    commit_message="Monthly rebuild from the catalog's archive",
)
PY
gh workflow run kaggle-mirror.yml -R "$repo" -f dataset=feed-history \
  -f title="Public-record events since 1851 (feed-history)" \
  -f subtitle="2.1M dated SEC, government, disaster and crypto events, each with its source"
rm -rf "$work"
echo "feed-history rebuilt from run $run; Kaggle mirror started"
