# 临时实验用的固定搜索结果；当前 main.py 流程直接使用此实现。
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
