"""Kommandozeile zum Testen des Agenten. Owner: Person B (B4).

    python -m agent.run                 # Chat im Terminal (InMemorySaver)
    python -m agent.run --sqlite        # mit SqliteSaver (wie die App)
    python -m agent.run --mermaid       # Graph als Mermaid nach docs/graph.mmd
    python -m agent.run --png           # Graph als PNG nach docs/graph.png (braucht Internet)
"""
import argparse
import uuid

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import config
from agent.graph import build_graph, sqlite_checkpointer
from agent.state import initial_state


def print_plan(plan: list[dict]) -> None:
    print(f"\n{'Datum':<11} {'Schicht':<11} {'Gäste':>5} {'Küche':>6} {'Service':>8} {'Abwasch':>8}")
    for r in plan:
        print(f"{r['date']:<11} {r['shift']:<11} {r['guests_planned']:>5} "
              f"{r['kueche']:>6} {r['service']:>8} {r['abwasch']:>8}")


def ask_human(payload: dict):
    """Fragt im Terminal nach und liefert den Wert für Command(resume=...)."""
    if payload["typ"] == "freigabe":
        print("\n" + (payload["erklaerung"] or ""))
        print_plan(payload["plan"])
        if payload.get("hinweis"):
            print("\nRückfrage:", payload["hinweis"])
        decision = input("\nfreigeben / anpassen / ablehnen: ").strip().lower()
        feedback = input("Was soll angepasst werden? ") if decision == "anpassen" else None
        return {"decision": decision, "feedback": feedback}
    return input(f"\nAgent: {payload['frage']}\nDu: ")


def chat(graph) -> None:
    config_run = {"configurable": {"thread_id": str(uuid.uuid4())}, "run_name": "gastroplanner"}
    print("Personalplanungsagent. Leere Eingabe beendet.")
    while text := input("\nDu: ").strip():
        result = graph.invoke(initial_state(text), config_run)
        while "__interrupt__" in result:
            resume = ask_human(result["__interrupt__"][0].value)
            result = graph.invoke(Command(resume=resume), config_run)
        print("\nAgent:", result["messages"][-1].content)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sqlite", action="store_true", help="SqliteSaver statt InMemorySaver")
    p.add_argument("--mermaid", action="store_true", help="Graph als docs/graph.mmd speichern")
    p.add_argument("--png", action="store_true", help="Graph als docs/graph.png speichern")
    args = p.parse_args()

    if args.mermaid or args.png:
        g = build_graph().get_graph()
        out = config.ROOT / "docs"
        out.mkdir(exist_ok=True)
        if args.mermaid:
            (out / "graph.mmd").write_text(g.draw_mermaid(), encoding="utf-8")
            print("docs/graph.mmd geschrieben")
        if args.png:
            (out / "graph.png").write_bytes(g.draw_mermaid_png())
            print("docs/graph.png geschrieben")
        return

    chat(build_graph(checkpointer=sqlite_checkpointer() if args.sqlite else InMemorySaver()))


if __name__ == "__main__":
    main()
