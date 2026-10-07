"""Terminal entry point: python -m workflows "your goal".

The heavy imports (the chat module builds the real tool registry and the
Gemini client) happen only after the arguments are checked, so --list and
argument errors never need an API key.
"""
import argparse
import sys

from workflows.executor import WorkflowExecutor
from workflows.gemini_planner import make_planner
from workflows.models import WorkflowStatus
from workflows.runner import list_runs, resume_workflow, run_goal
from workflows.store import WorkflowStore

DEADLINE_SECONDS = 600.0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m workflows",
        description="Plan a goal with Nova, review it, ask before running, then run it.",
    )
    parser.add_argument("goal", nargs="*", help="what you want done, in plain words")
    parser.add_argument("--resume", metavar="ID", help="continue a saved workflow")
    parser.add_argument("--list", action="store_true", help="show saved workflows")
    parser.add_argument(
        "--write-tools",
        action="store_true",
        help="let plans use tools that change things (each write still asks you first)",
    )
    parser.add_argument(
        "--no-critic", action="store_true", help="skip the extra model review of the plan"
    )
    return parser


def main(argv: list[str] | None = None, store: WorkflowStore | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    goal = " ".join(args.goal).strip()
    if sum([bool(goal), bool(args.resume), bool(args.list)]) != 1:
        parser.error("give a goal, or use exactly one of --resume ID or --list")
    store = store if store is not None else WorkflowStore()

    if args.list:
        list_runs(store)
        return 0

    # Same registry and approval prompt as chat, so workflows behave the same way.
    from app.chat import registry
    from app.llm import ask as model

    def make_executor(on_event):
        return WorkflowExecutor(
            registry, on_event=on_event, model=model, deadline_seconds=DEADLINE_SECONDS
        )

    if args.resume:
        result = resume_workflow(args.resume, make_executor, store)
    else:
        planner = make_planner(
            registry,
            generate=model,
            read_only_only=not args.write_tools,
            critic=not args.no_critic,
        )
        result = run_goal(goal, planner, make_executor, store)
    return 0 if result is not None and result.status is WorkflowStatus.SUCCEEDED else 1


if __name__ == "__main__":
    sys.exit(main())