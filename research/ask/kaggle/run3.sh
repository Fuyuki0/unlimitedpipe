#!/bin/sh
# Build 3 on Kaggle's free GPU (a token in ~/.kaggle/access_token):
#   run3.sh data       upload the build 3 public examples and the real-question test set
#   run3.sh train      train the build 3 model (job unlimitedpipe-ask-v3-train)
#   run3.sh compare NAME 'LABEL=SOURCE' ...   grade models (job unlimitedpipe-ask-NAME)
# A SOURCE is a Hugging Face id, or kernel:SLUG for a model an earlier job trained.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
kaggle="$here/../../../.venv/bin/kaggle"
user="${KAGGLE_USER:-fuyuki0}"

upload() {  # upload SLUG TITLE FILE...
  slug="$1"; title="$2"; shift 2
  stage="$(mktemp -d)"
  cp "$@" "$stage/"
  printf '{"title": "%s", "id": "%s/%s", "licenses": [{"name": "other"}]}\n' "$title" "$user" "$slug" \
    > "$stage/dataset-metadata.json"
  if "$kaggle" datasets status "$user/$slug" >/dev/null 2>&1; then
    "$kaggle" datasets version -p "$stage" -m "Rebuilt" -q
  else
    "$kaggle" datasets create -p "$stage" -q   # private unless --public
  fi
}

push() {  # push SLUG TITLE CODE DATASETS KERNELS
  job="$(mktemp -d)"
  cp "$3" "$job/job.py"
  cat > "$job/kernel-metadata.json" <<META
{"id": "$user/$1", "title": "$2", "code_file": "job.py", "language": "python",
 "kernel_type": "script", "is_private": true, "enable_gpu": true, "enable_internet": true,
 "dataset_sources": [$4], "competition_sources": [], "kernel_sources": [$5]}
META
  "$kaggle" kernels push -p "$job"
  echo "Status: $kaggle kernels status $user/$1"
}

case "${1:-}" in
  data)
    upload unlimitedpipe-ask-sft-public-v3 "unlimitedpipe ask-sft-public v3" \
      "$here/../data-public/train.jsonl" "$here/../data-public/test.jsonl"
    upload unlimitedpipe-ask-real "unlimitedpipe ask real" "$here/../real/test.jsonl" \
      "$here/../real/extra.jsonl"
    ;;
  data4)
    upload unlimitedpipe-ask-sft-public-v4 "unlimitedpipe ask-sft-public v4" \
      "$here/../data-public/train.jsonl" "$here/../data-public/test.jsonl"
    upload unlimitedpipe-ask-real "unlimitedpipe ask real" "$here/../real/test.jsonl" \
      "$here/../real/extra.jsonl"
    ;;
  real)
    upload unlimitedpipe-ask-real "unlimitedpipe ask real" "$here/../real/test.jsonl" \
      "$here/../real/extra.jsonl" "$here/../real/blind.jsonl"
    ;;
  train4)
    push unlimitedpipe-ask-v4-train "unlimitedpipe ask v4 train" "$here/train.py" \
      "\"$user/unlimitedpipe-ask-sft-public-v4\"" ""
    ;;
  train)
    push unlimitedpipe-ask-v3-train "unlimitedpipe ask v3 train" "$here/train.py" \
      "\"$user/unlimitedpipe-ask-sft-public-v3\"" ""
    ;;
  compare)
    name="$2"; shift 2
    models="$(python3 -c 'import json,sys; print(json.dumps(dict(a.split("=",1) for a in sys.argv[1:])))' "$@")"
    code="$(mktemp -d)/compare.py"
    python3 - "$here/compare3.py" "$code" "$models" <<'PY'
import sys
src, dst, models = sys.argv[1:4]
text = open(src).read().replace("MODELS = {}", "MODELS = " + models, 1)
open(dst, "w").write(text)
PY
    kernels="$(for a in "$@"; do case "$a" in *=kernel:*) printf '"%s/%s",' "$user" "${a#*=kernel:}";; esac; done)"
    # DATASETS="a b" attaches only those test sets (default: all of them).
    sets="${DATASETS:-unlimitedpipe-ask-real unlimitedpipe-ask-sft-public-v4 unlimitedpipe-ask-sft-public-v3 unlimitedpipe-ask-sft-public unlimitedpipe-ask-sft}"
    datasets="$(for d in $sets; do printf '"%s/%s",' "$user" "$d"; done)"
    push "unlimitedpipe-ask-$name" "unlimitedpipe ask $name" "$code" "${datasets%,}" "${kernels%,}"
    ;;
  *) echo "usage: run3.sh data | train | compare NAME LABEL=SOURCE..." >&2; exit 2 ;;
esac
