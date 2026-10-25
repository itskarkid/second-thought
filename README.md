# Local Ollama Chat

A small Python/Flask app with local OpenAI Privacy Filter detection and browser-based masking review. No OpenAI API key is needed.

## Run

Requires Python 3.10+, Git (for the official `opf` package), and Ollama. Detection runs on CPU by default.

```powershell
python -m pip install -r requirements.txt
ollama pull llama3.2:3b
ollama serve
```

If Ollama is already running, skip `ollama serve`. In another terminal:

```powershell
python main.py
```

Open <http://127.0.0.1:5000>. To use another port, set `$env:PORT = "5001"` before running. The model field can use any installed Ollama chat model. Open the app through Flask, not the HTML file directly.

The first non-empty privacy review downloads the `openai/privacy-filter` checkpoint (about 2.8 GB) to `~/.opf/privacy_filter` and loads it into memory. Allow extra time and several GB of available RAM. Later requests reuse the model. To prepare it before starting Flask:

```powershell
python -c "from privacy import detect_tokens; print(detect_tokens('My name is Alice Smith.'))"
```

Set `$env:OPF_CHECKPOINT = "D:\models\privacy_filter"` to use an existing checkpoint directory. After the weights and tokenizer resources have been cached, inference runs locally. Set `$env:PRIVACY_DEVICE = "cuda"` only with an NVIDIA GPU and a CUDA-enabled PyTorch installation. `opf` is OpenAI's official Python runtime; Ollama is used only for chat.

After editing the HTML template, restart `python main.py` (Ctrl+C, then run it again) and refresh the browser. Flask runs without debug mode and can cache an older template.

## Privacy Review

- Chat messages scroll above the bottom composer. With privacy review on, the input and outgoing preview remain side by side. After a 500 ms typing pause, the original draft is sent to the local Flask `/detect` endpoint. Python runs detection locally; it does not send the draft to Ollama or a cloud inference service.
- OpenAI Privacy Filter suggests names, emails, phone numbers, addresses, account numbers, dates, URLs, and secrets. It analyzes the whole draft, including multi-word entities, using the official runtime's span decoding. Detection can miss private information or flag harmless text; it is not an anonymity guarantee.
- Click highlighted spans directly in **Message to Ollama** to replace them with their bracketed label, such as `[private_person]` or `[private_email]`; click again to restore. Unhighlighted words can also be masked using `[MASKED]`. Suggestions are not automatically masked. **Send** submits the exact reviewed text to Ollama without a separate confirmation dialog.
- Send is disabled while the current draft is awaiting detection or detection has failed. **Retry detection** retries a failure. There is no silent regex fallback. Privacy review supports up to 4,000 characters without truncation; inference requests are serialized to limit memory usage.
- Edit before sending. Masking choices are retained for unchanged segments before and after the edited region; model boundary changes require reviewing again. Stale detection responses are ignored. Failed chat requests retain the draft and masking choices for retry.
- With privacy review off, the entire outgoing preview section is hidden, the input expands to full width, and **Send** uses the original input without masking. Turning privacy review back on restores the preview and existing masking choices.
- Only accepted text is added to chat history and sent with later messages. Switching privacy on cannot retract information sent earlier; start a new chat to clear the current history.
- Requests are limited to 1 MiB of encoded JSON, including all chat history. History is never silently truncated. If a request is too large, shorten the draft, or copy it before clicking **New chat** and paste it into the new conversation. Repeating the same oversized request will not succeed; the draft and masking choices are kept until you edit or clear them.
- No chat or draft is saved by this app. Drafts exist in browser and Python process memory during review; masking is not secure memory erasure. Detection responses use `Cache-Control: no-store`. Ollama receives the accepted text and may have its own retention behavior. Avoid enabling request-body logging in proxies or debugging middleware.
- Detection failures log only the processing stage and exception class to the server console. Exception messages and tracebacks are deliberately omitted because they may contain private input. The browser receives a generic error.
- The app calls Ollama on localhost, uses no external UI assets, and binds only to `127.0.0.1`. Model and tokenizer downloads use external hosts, but inference is local. This is a local demo, not a production authenticated service.

## Customize Masking

Edit `filter_token(text, label)` in `privacy.py`. `PRIVATE_LABELS` chooses which of the model's detected categories are highlighted and replaced with `[label]`. `MASK_VALUE` sets the fallback replacement for unlabelled or unsupported categories. This post-processing does not retrain the model or add new detection categories. JavaScript only renders Python's exact segments and applies your manual choices.

For category-specific replacements:

- Set `maskValue` to `"[EMAIL]" if label == "private_email" else MASK_VALUE`.

Surrounding punctuation and whitespace are kept outside clickable segments; masking `Vance,` when detected as a person produces `[private_person],`. Multi-word private spans are grouped for review. The browser receives exact strings rather than converting Python character offsets to JavaScript offsets, avoiding Unicode alignment errors. Privacy review off skips detection and sends the original input.

## Tests

```powershell
python -m unittest -v
node test_chat.js
```

Unit tests mock model inference and do not require a model download. The preparation command above exercises the real detector.

## Before Committing

The `.gitignore` excludes virtual environments, Python caches, local `.env` files, and common checkpoint locations and weight files. Keep downloaded models and private sample data out of the repository. Ignore rules do not remove files that Git already tracks.

Before committing, inspect `git status --short` and `git diff --cached` to confirm that only intended source, tests, and documentation are staged.