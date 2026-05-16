"""Post-pitch feedback report generator for Shark Tank simulator."""

from statistics import mean

JUDGE_NAMES = {"cuban": "Mark Cuban", "oleary": "Kevin O'Leary",
               "corcoran": "Barbara Corcoran", "herjavec": "Robert Herjavec",
               "greiner": "Lori Greiner"}


def _label(s):
    return "shaky" if s < 0.4 else "steady" if s < 0.7 else "confident"


def _judge_name(k):
    return JUDGE_NAMES.get(k, k.title())


def generate_report(session_data: dict) -> dict:
    """Build a structured feedback report from a session log."""
    session_id = session_data.get("session_id", "unknown")
    turns = session_data.get("turns", [])

    if not turns:
        return {"session_id": session_id,
                "summary_text": "No pitch recorded. Take a turn to get feedback.",
                "overall_confidence": 0.5, "confidence_trajectory": [],
                "hardest_judge": "cuban", "judge_turn_counts": {},
                "tough_moments": [],
                "suggestions": ["Aim for 90-second pitches with one memorable statistic."]}

    moods = [float(t.get("mood", 0.5)) for t in turns]
    overall = mean(moods)

    judge_counts, judge_moods = {}, {}
    for t, m in zip(turns, moods):
        j = t.get("judge", "cuban")
        judge_counts[j] = judge_counts.get(j, 0) + 1
        judge_moods.setdefault(j, []).append(m)

    averages = {j: mean(ms) for j, ms in judge_moods.items()}
    min_avg = min(averages.values())
    candidates = [j for j, a in averages.items() if a == min_avg]
    hardest = "cuban" if "cuban" in candidates else sorted(candidates)[0]

    tough_moments = []
    for i in range(len(turns) - 1):
        if moods[i + 1] - moods[i] < -0.15:
            tough_moments.append({"turn_idx": turns[i + 1].get("turn_idx", i + 1),
                                  "judge": turns[i + 1].get("judge", "cuban"),
                                  "response": turns[i + 1].get("response", ""),
                                  "mood_before": round(moods[i], 2),
                                  "mood_after": round(moods[i + 1], 2)})

    suggestions = []
    if overall < 0.4:
        suggestions.append("Practice opening with concrete numbers — your delivery sounded uncertain.")
    if hardest == "oleary":
        suggestions.append("Have a clear royalty/exit answer ready — O'Leary will press on it.")
    elif hardest == "cuban":
        suggestions.append("Memorize CAC, LTV, and gross margin — Cuban hits these first.")
    elif hardest == "corcoran":
        suggestions.append("Practice your personal story — Barbara invests in founders, not slides.")
    if tough_moments:
        suggestions.append(
            f"Watch the moment at turn {tough_moments[0]['turn_idx']} — "
            "your confidence dropped sharply. Plan a recovery line.")
    suggestions.append("Aim for 90-second pitches with one memorable statistic.")

    lead = suggestions[0] if suggestions else "keep practicing."
    summary_text = (f"{_label(overall).capitalize()} delivery overall ({overall:.2f}). "
                    f"{_judge_name(hardest)} was the toughest read — {lead}")

    return {"session_id": session_id, "summary_text": summary_text,
            "overall_confidence": round(overall, 3),
            "confidence_trajectory": [round(m, 2) for m in moods],
            "hardest_judge": hardest, "judge_turn_counts": judge_counts,
            "tough_moments": tough_moments, "suggestions": suggestions}


def format_markdown(report: dict) -> str:
    """Render the report dict as a human-readable markdown string for display."""
    conf = report["overall_confidence"]
    traj = report["confidence_trajectory"]
    parts = [f"# Pitch Debrief — session {report['session_id']}", "",
             f"**Overall confidence**: {conf:.2f} ({_label(conf)})",
             f"**Hardest judge**: {_judge_name(report['hardest_judge'])}",
             f"**Turns taken**: {sum(report['judge_turn_counts'].values())}", "",
             "## Trajectory",
             " -> ".join(f"{m:.2f}" for m in traj) if traj else "_no turns_", "",
             "## Tough moments"]
    if report["tough_moments"]:
        for tm in report["tough_moments"]:
            parts.append(f"- Turn {tm['turn_idx']}: confidence dropped from "
                         f"{tm['mood_before']:.2f} to {tm['mood_after']:.2f} after "
                         f"{_judge_name(tm['judge'])}'s \"{tm['response']}\"")
    else:
        parts.append("_none_")
    parts.extend(["", "## Suggestions"])
    parts.extend(f"- {s}" for s in report["suggestions"])
    parts.extend(["", "## Summary", report["summary_text"]])
    return "\n".join(parts)


if __name__ == "__main__":
    sample = {"session_id": "test01", "turns": [
        {"turn_idx": 0, "judge": "cuban", "transcript": "p", "response": "r", "mood": 0.6, "latency_ms": 2000},
        {"turn_idx": 1, "judge": "oleary", "transcript": "p", "response": "r", "mood": 0.35, "latency_ms": 2100},
        {"turn_idx": 2, "judge": "corcoran", "transcript": "p", "response": "r", "mood": 0.55, "latency_ms": 1900}]}
    report = generate_report(sample)
    assert report["hardest_judge"] == "oleary"
    assert len(report["tough_moments"]) >= 1
    assert any("O'Leary" in s or "royalty" in s.lower() for s in report["suggestions"])
    md = format_markdown(report)
    print(md)
    print("\nPASS")
