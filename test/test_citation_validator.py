from citation_validator import validate_citations


SOURCES = [
    {
        "title": "Python 官方文档",
        "url": "https://docs.python.org/3/",
        "snippet": "Python 官方语言与标准库文档。",
    },
    {
        "title": "Python 教程",
        "url": "https://docs.python.org/3/tutorial/",
        "snippet": "面向初学者的 Python 教程。",
    },
]

VALID_ANSWER = """Python 是一种通用编程语言。[1]

初学者可以从官方教程开始学习。[2]

## 参考资料
[1] Python 官方文档：https://docs.python.org/3/
[2] Python 教程：https://docs.python.org/3/tutorial/
"""


def test_valid_answer_passes():
    is_valid, feedback = validate_citations(VALID_ANSWER, SOURCES)
    assert is_valid is True, feedback


def test_answer_without_inline_citation_fails():
    answer = """Python 是一种通用编程语言。

## 参考资料
[1] Python 官方文档：https://docs.python.org/3/
[2] Python 教程：https://docs.python.org/3/tutorial/
"""
    is_valid, _ = validate_citations(answer, SOURCES)
    assert is_valid is False


def test_answer_without_references_section_fails():
    is_valid, _ = validate_citations("Python 是一种通用编程语言。[1]", SOURCES)
    assert is_valid is False


def test_unknown_inline_citation_fails():
    answer = VALID_ANSWER.replace(
        "初学者可以从官方教程开始学习。[2]",
        "初学者可以从官方教程开始学习。[3]",
    )
    is_valid, _ = validate_citations(answer, SOURCES)
    assert is_valid is False


def test_unknown_reference_url_fails():
    answer = VALID_ANSWER.replace(
        "https://docs.python.org/3/tutorial/",
        "https://example.com/fake-source",
    )
    is_valid, _ = validate_citations(answer, SOURCES)
    assert is_valid is False


def test_extra_unknown_reference_url_fails():
    answer = VALID_ANSWER + "\n[3] 虚构资料：https://example.com/fake-source\n"
    is_valid, _ = validate_citations(answer, SOURCES)
    assert is_valid is False
