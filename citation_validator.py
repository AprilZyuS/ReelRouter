import re


def validate_citations(
    answer: str,
    sources: list[dict[str, str]],
) -> tuple[bool, str]:
    """校验正文引用编号与参考资料是否和已提供的 sources 一致。"""
    if "参考资料" not in answer:
        return False, "答案中缺少参考资料部分。"

    body, references = answer.split("参考资料", maxsplit=1)
    citation_numbers = {int(number) for number in re.findall(r"\[(\d+)\]", body)}

    if not citation_numbers:
        return False, "正文中缺少对参考资料的引用标注，例如 [1]。"

    invalid_numbers = sorted(
        number for number in citation_numbers if number < 1 or number > len(sources)
    )
    if invalid_numbers:
        invalid_text = ", ".join(f"[{number}]" for number in invalid_numbers)
        return False, f"正文中引用了未提供的参考资料：{invalid_text}。"

    source_urls = {source["url"] for source in sources}
    reference_urls = set(re.findall(r"https?://[^\s\])，。]+", references))
    unknown_urls = reference_urls - source_urls
    if unknown_urls:
        return False, "参考资料中包含未提供的 URL。"

    for number in citation_numbers:
        source = sources[number - 1]
        if f"[{number}]" not in references or source["url"] not in references:
            return False, f"参考资料部分缺少 [{number}] 对应的来源信息。"

    return True, ""
