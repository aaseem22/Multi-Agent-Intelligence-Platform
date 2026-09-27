from app.core.llm import MAX_SERVER_DELAY_SECONDS, server_retry_delay


def test_server_retry_delay_parses_gemini_retry_info():
    exc = RuntimeError(
        "429 RESOURCE_EXHAUSTED ... Please retry in 54.716655484s. 'retryDelay': '54s'"
    )
    assert server_retry_delay(exc) == 54.716655484


def test_server_retry_delay_is_capped_and_optional():
    assert server_retry_delay(RuntimeError("retry in 900s")) == MAX_SERVER_DELAY_SECONDS
    assert server_retry_delay(RuntimeError("503 UNAVAILABLE")) is None
