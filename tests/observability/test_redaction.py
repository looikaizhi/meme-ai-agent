"""Tests for secret redaction logging filter."""
import io
import logging

from memedog.observability.redaction import SecretRedactingFilter, install_redaction


def _record(msg, args=()):
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)


def test_filter_scrubs_api_key_pattern():
    f = SecretRedactingFilter()
    rec = _record("calling https://x.com/?api-key=ABC123secretXYZ&z=1")
    f.filter(rec)
    assert "ABC123secretXYZ" not in rec.getMessage()
    assert "api-key=***" in rec.getMessage()


def test_filter_scrubs_telegram_token():
    f = SecretRedactingFilter()
    rec = _record("POST https://api.telegram.org/bot7423235860:AAExampleTokenValue/send")
    f.filter(rec)
    assert "AAExampleTokenValue" not in rec.getMessage()
    assert "bot***" in rec.getMessage()


def test_filter_scrubs_exact_secret_value():
    f = SecretRedactingFilter(secrets=["super-secret-key-1234"])
    rec = _record("loaded key super-secret-key-1234 ok")
    f.filter(rec)
    assert "super-secret-key-1234" not in rec.getMessage()
    assert "***" in rec.getMessage()


def test_filter_scrubs_through_args():
    f = SecretRedactingFilter()
    rec = _record("url=%s", ("https://x?api-key=SECRETVAL123456",))
    f.filter(rec)
    assert "SECRETVAL123456" not in rec.getMessage()
    assert rec.args in ((), None)


def test_filter_never_raises_on_bad_record():
    f = SecretRedactingFilter()

    class Boom:
        def __str__(self):
            raise ValueError("boom")

    rec = _record("%s", (Boom(),))
    assert f.filter(rec) is True  # must not raise


def test_install_redaction_wires_handlers_for_child_loggers():
    root = logging.getLogger()
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    try:
        class _S:
            helius_api_key = "HELIUSKEY1234567"
            rugcheck_api_key = None
            twitter_bearer = None
            openai_api_key = None
            anthropic_api_key = None
            deepseek_api_key = None
            telegram_bot_token = None

        install_redaction(_S())
        logging.getLogger("memedog.clients.helius").warning(
            "rpc https://x/?api-key=HELIUSKEY1234567"
        )
        handler.flush()
        out = buf.getvalue()
        assert "HELIUSKEY1234567" not in out
        assert "***" in out
    finally:
        root.removeHandler(handler)
        # remove the filter we installed so other tests are unaffected
        for filt in list(root.filters):
            root.removeFilter(filt)
