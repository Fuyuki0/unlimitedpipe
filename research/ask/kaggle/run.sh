#!/bin/sh
# Train the ask model on Kaggle's free GPU through the Kaggle API (a token in
# ~/.kaggle/access_token). The examples go up as a private Kaggle dataset; the trained GGUF
# comes back into research/ask/kaggle/output. Nothing needs a Hugging Face token on Kaggle.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
kaggle="$here/../../../.venv/bin/kaggle"
user="$(python3 -c "import json,os; p=os.path.expanduser('~/.kaggle/kaggle.json'); print(json.load(open(p))['username'])" 2>/dev/null || "$kaggle" config view 2>/dev/null | awk '/username/{print $NF}')"
user="${KAGGLE_USER:-$user}"
stage="$(mktemp -d)"
cp "$here/../data/train.jsonl" "$here/../data/test.jsonl" "$stage/"
cat > "$stage/dataset-metadata.json" <<META
{"title": "unlimitedpipe ask-sft", "id": "$user/unlimitedpipe-ask-sft", "licenses": [{"name": "other"}]}
META
if "$kaggle" datasets status "$user/unlimitedpipe-ask-sft" >/dev/null 2>&1; then
  "$kaggle" datasets version -p "$stage" -m "Rebuilt examples" -q
else
  "$kaggle" datasets create -p "$stage" -q   # private unless --public
fi
for _ in $(seq 1 60); do   # the job can only use the dataset once Kaggle has processed it
  "$kaggle" datasets status "$user/unlimitedpipe-ask-sft" 2>/dev/null | grep -qi ready && break
  python3 -c "import time; time.sleep(10)"
done
job="$(mktemp -d)"
cp "$here/train.py" "$job/"
cat > "$job/kernel-metadata.json" <<META
{"id": "$user/unlimitedpipe-ask-train", "title": "unlimitedpipe ask train", "code_file": "train.py",
 "language": "python", "kernel_type": "script", "is_private": true, "enable_gpu": true,
 "enable_internet": true, "dataset_sources": ["$user/unlimitedpipe-ask-sft"],
 "competition_sources": [], "kernel_sources": []}
META
"$kaggle" kernels push -p "$job"
echo "Pushed. Status: $kaggle kernels status $user/unlimitedpipe-ask-train"
