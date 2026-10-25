import logging
import os
import re
from threading import Lock


MAX_DETECTION_CHARS = 4000
MASK_VALUE = "[MASKED]"
PRIVATE_LABELS = {
    "account_number", "private_address", "private_email", "private_person",
    "private_phone", "private_url", "private_date", "secret",
}
_redactor = None
_inference_lock = Lock()
_logger = logging.getLogger(__name__)


class DetectionUnavailable(Exception):
    pass


def get_redactor():
    global _redactor
    if _redactor is None:
        from opf import OPF

        _redactor = OPF(device=os.environ.get("PRIVACY_DEVICE", "cpu"))
    return _redactor


def filter_token(text, label=None):
    return {
        "text": text,
        "suggested": label in PRIVATE_LABELS,
        "maskValue": f"[{label}]" if label in PRIVATE_LABELS else MASK_VALUE,
        "maskable": any(character.isalnum() or character == "@" for character in text),
        "label": label,
    }


def plain_tokens(text):
    result = []
    for part in re.findall(r"\s+|\S+", text):
        start = 0
        end = len(part)
        while start < end and not (part[start].isalnum() or part[start] == "@"):
            start += 1
        while end > start and not (part[end - 1].isalnum() or part[end - 1] == "@"):
            end -= 1
        result.extend(filter_token(piece) for piece in (part[:start], part[start:end], part[end:]) if piece)
    return result


def detect_tokens(text):
    if not text.strip():
        return plain_tokens(text)
    if not _inference_lock.acquire(blocking=False):
        raise DetectionUnavailable("Privacy detection is busy. Retry shortly.")
    stage = "model initialization"
    try:
        redactor = get_redactor()
        stage = "model inference"
        prediction = redactor.redact(text)
        stage = "span validation"
        if prediction.warning or prediction.text != text:
            raise ValueError("Tokenizer changed the input")
        tokens = []
        cursor = 0
        for span in sorted(prediction.detected_spans, key=lambda item: item.start):
            if not (cursor <= span.start < span.end <= len(text)):
                raise ValueError("Invalid or overlapping privacy spans")
            if text[span.start:span.end] != span.text:
                raise ValueError("Privacy span does not match input")
            start, end = span.start, span.end
            while start < end and not (text[start].isalnum() or text[start] == "@"):
                start += 1
            while end > start and not (text[end - 1].isalnum() or text[end - 1] == "@"):
                end -= 1
            tokens.extend(plain_tokens(text[cursor:start]))
            if start < end:
                tokens.append(filter_token(text[start:end], span.label))
            tokens.extend(plain_tokens(text[end:span.end]))
            cursor = span.end
        tokens.extend(plain_tokens(text[cursor:]))
        return tokens
    except DetectionUnavailable:
        raise
    except Exception as error:
        # Exception messages and tracebacks may contain the private draft.
        _logger.error(
            "Privacy detection failed during %s (%s). Exception details omitted to protect private input.",
            stage, type(error).__name__,
        )
        raise DetectionUnavailable(
            "Privacy detection unavailable. Check the Python dependencies and local model checkpoint."
        ) from None
    finally:
        _inference_lock.release()