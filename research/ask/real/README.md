# Real questions

Test questions written the way people type them into `unlimited ask`, in English and Thai:
"bitcoin price?", "whats new with bitget", "ข่าวไทยวันนี้มีอะไรบ้าง". The template test sets
of `build.py` are generated from the same patterns the model trains on; these are not, so they
are the honest check.

- [`questions.txt`](questions.txt): the questions, including some the catalog cannot answer.
- [`freeze.py`](freeze.py): puts each question through `ask`'s own search on a saved catalog
  and keeps the exact prompt a model would get. Questions `ask` answers without a model
  (nothing found, or only half a match) are left out: they test the search, not the model.
- `test.jsonl` (private: it holds publishers' headlines): the frozen prompts, each labelled by
  hand with the kind of answer it needs (a fact, a list, or "the sources do not say") and the
  numbers of the sources that answer it.

Frozen on 2026-09-27 from the public catalog: 70 questions reach a model (48 lists, 14
facts, 8 the sources do not answer; 51 in English, 19 in Thai).
