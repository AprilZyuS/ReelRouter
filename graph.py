from nodes import researcher, reviewer, supervisor, writer
from workflow import build_graph
from langgraph.checkpoint.memory import InMemorySaver
from human_review import human_review

checkpointer = InMemorySaver()

graph = build_graph(
    researcher = researcher,
    reviewer = reviewer,
    writer = writer,
    supervisor = supervisor,
    human_review= human_review,
    checkpointer = checkpointer
)
