from graph import graph
from config import settings
from langgraph.types import Command

THREAD_ID = "python-research-demo-001"

config= {
        "configurable": {"thread_id": THREAD_ID,},
        "recursion_limit": settings.recursion_limit
        }

result = graph.invoke(
    {
        "task": "Write a research paper on Python programming.",
        "research": "",
        "answer": "",
        "review_status": "",
        "review_feedback": "",
        "next_agent": "",
        "retry_count": 0,
        "sources":[],
        "human_choice": "",
    },
    config= config
    
)

while "__interrupt__" in result:
    payload = result["__interrupt__"][0].value

    print("\n自动修改次数已用完。")
    print("Reviewer 意见：", payload["review_feedback"])
    print("当前回答：", payload["answer"])

    action = input("请选择 continue / accept / end：").strip().lower()

    while action not in {"continue", "accept", "end"}:
        action = input("输入无效，请重新输入 continue / accept / end：").strip().lower()

    feedback = ""
    if action == "continue":
        feedback = input("请输入给 Writer 的补充意见：").strip()

    result = graph.invoke(
        Command(
            resume={
                "action": action,
                "feedback": feedback,
            }
        ),
        config=config,
    )
    

snapshot = graph.get_state(config)
history = list(graph.get_state_history(config))

for index, snapshot in enumerate(reversed(history), start=1):
    values = snapshot.values

    print(f"\n===== Checkpoint {index} =====")
    print("下一步：", snapshot.next)
    print("research 是否存在：", bool(values.get("research")))
    print("answer 是否存在：", bool(values.get("answer")))
    print("审稿状态：", values.get("review_status"))
    print("重试次数：", values.get("retry_count"))
