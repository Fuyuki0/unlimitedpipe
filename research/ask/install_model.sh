#!/bin/sh
# Download the trained `ask` model from Hugging Face (private: needs `hf auth login` with
# access to the unlimitedpipe organization) and add it to Ollama as unlimitedpipe-ask:0.5b,
# with the same chat template as qwen2.5, which it was trained from.
set -eu
dir="${HOME}/.cache/unlimitedpipe/models"
hf="$(dirname "$0")/../../.venv/bin/hf"
"$hf" download unlimitedpipe/ask-0.5b-GGUF ask-0.5b-q8_0.gguf --local-dir "$dir" >/dev/null
ollama pull qwen2.5:0.5b >/dev/null
ollama show --modelfile qwen2.5:0.5b | sed "s#^FROM .*#FROM ${dir}/ask-0.5b-q8_0.gguf#" > "${dir}/Modelfile"
ollama create unlimitedpipe-ask:0.5b -f "${dir}/Modelfile"
echo 'Try: unlimited ask "what is the bitcoin price today?" --model unlimitedpipe-ask:0.5b'
