import json

FALLBACK = (
    "needs_revision",
    "Reviewer 输出格式错误，请重新检查答案完整性。"
)

def parse_review_response(raw:str) -> tuple[str, str]:
    """
    解析审稿人输出的 JSON 字符串，返回状态和反馈信息。
    如果解析失败，返回默认的 needs_revision 状态和错误提示。
    """
    try:
        raw = raw.strip()   
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1]).strip()

        result = json.loads(raw)
        if not isinstance(result, dict):
            return FALLBACK
        
    except (json.JSONDecodeError, KeyError):
        return FALLBACK

    if "status" not in result or "feedback" not in result:
        return FALLBACK

    status = result.get("status", "needs_revision")
    feedback = result.get("feedback", "")
    
    if not isinstance(status, str) or not isinstance(feedback, str):
        return FALLBACK

    status = status.strip().lower()
    feedback = feedback.strip()

    if status not in {"approved", "needs_revision"}:
        return FALLBACK

    return (status, feedback)