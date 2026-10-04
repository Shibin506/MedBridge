# Phase 1: from discharge paper to verified data

**Goal:** turn an uploaded discharge document into structured data we can trust enough to build
the rest of the product on.

## The pipeline

```
PDF/.txt  ->  documents.py   plain text
          ->  extractor.py   LLM fills an ExtractionDraft (schema-constrained JSON)
          ->  verify.py      code checks every item's quote against the text
          ->  ExtractionResult  (each item: grounded? needs_confirmation? why?)
          ->  main.py        POST /extract
```

## Key ideas

1. **Schema first (`schemas.py`).** "Medication", "FollowUp", ... are the vocabulary of the whole
   app. The API's structured-output feature forces the model to return JSON matching the schema,
   so we never parse free text.
2. **Evidence for every item.** The model must copy a verbatim `source_quote` for each item.
3. **The model proposes, code verifies (`verify.py`).** We check the quote really exists in the
   document (after normalizing whitespace/quotes/hyphenation) and that a drug's name is in its own
   quote. A made-up item cannot pass this check. Failing items get `needs_confirmation=True`.
   The LLM never decides `grounded`; only our code does.
4. **The human confirms.** Phase 2's confirm screen shows "your paper" next to "what we understood".
5. **Prefer doubt to guessing.** Missing info is `null`; ambiguity goes in `unclear_items`.
6. **The document is data, not instructions.** The prompt tells the model to ignore commands that
   appear inside the document.
7. **Testable without the network.** `Extractor` takes an injected client, so tests use a fake.

## Where things are

| File | Role |
|---|---|
| `app/schemas.py` | Draft models (LLM) and result models (code-verified) |
| `app/documents.py` | PDF/txt -> text; rejects scans (OCR/vision comes later) |
| `app/extractor.py` | The one LLM call (prompt + structured output) |
| `app/verify.py` | Grounding checks |
| `app/main.py` | FastAPI app: `GET /health`, `POST /extract` |
| `samples/` | 3 synthetic discharge documents (txt + pdf) |
| `scripts/try_extract.py` | Run the real extractor from the command line |

## Known limits (on purpose, for now)

- Scanned/photo documents are rejected (planned: vision input).
- Grounding is exact-after-normalizing. A correct but slightly misquoted item gets flagged; that is
  the safe direction to fail.
- Grounding proves the item was *in the document*, not that the model *interpreted it correctly*
  (e.g. status `stop` vs `continue`). That is what the patient confirm step is for.
