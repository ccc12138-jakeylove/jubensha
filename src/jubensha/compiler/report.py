from jubensha.schema.ir import LinterReport, Script


def render_lint_report(script: Script, report: LinterReport) -> str:
    path = report.solvability.optimal_path_clue_ids
    names = [script.clues[key].display_name for key in path if key in script.clues]
    lines = [f"## {script.title} 质检", f"状态：{'可进入人工校对' if report.passed else '不可发布'}",
             f"难度估计：{report.difficulty}/5 · 红鲱鱼占比：{report.red_herring_ratio:.0%}",
             f"最短关键证据路径：{' → '.join(names) if names else '未找到'}",
             f"路径成本：{report.solvability.minimum_cost if report.solvability.minimum_cost is not None else '未知'} / 搜证预算：{report.solvability.search_budget}"]
    for issue in report.blockers + report.warnings:
        lines.append(f"- [{issue.severity}] {issue.message}"
                    + (f"。建议：{issue.suggestion}" if issue.suggestion else ""))
    lines.append("最短路径是结构参考，仍需作者核对语义上是否足以推理。")
    return "\n\n".join(lines)
