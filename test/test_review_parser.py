from review_parser import parse_review_response


FALLBACK = (
    "needs_revision",
    "Reviewer 输出格式错误，请重新检查答案完整性。",
)


def test_approved_json_is_parsed():
    assert parse_review_response(
        '{"status": "approved", "feedback": ""}'
    ) == ("approved", "")


def test_needs_revision_json_is_parsed():
    assert parse_review_response(
        '{"status": "needs_revision", "feedback": "缺少学习路线。"}'
    ) == ("needs_revision", "缺少学习路线。")


def test_json_in_markdown_code_block_is_parsed():
    assert parse_review_response(
        '```json\n{"status": "approved", "feedback": ""}\n```'
    ) == ("approved", "")


def test_plain_text_uses_fallback():
    assert parse_review_response("答案看起来不错，我建议通过。") == FALLBACK


def test_invalid_status_and_non_string_feedback_use_fallback():
    assert parse_review_response(
        '{"status": "unknown", "feedback": 123}'
    ) == FALLBACK


def test_invalid_status_uses_fallback():
    assert parse_review_response(
        '{"status": "unknown", "feedback": "任意文本"}'
    ) == FALLBACK


def test_missing_feedback_uses_fallback():
    assert parse_review_response('{"status": "approved"}') == FALLBACK
