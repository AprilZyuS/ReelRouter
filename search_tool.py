#此为实验，main.py中写死
def mock_search(query: str) -> list[dict[str, str]]:
    return [
        {
            "title": "Python 官方文档",
            "url": "https://docs.python.org/3/",
            "snippet": "Python 官方语言与标准库文档。",
        },
        {
            "title": "Python 教程",
            "url": "https://docs.python.org/3/tutorial/",
            "snippet": "面向初学者的 Python 教程。",
        }
    ]