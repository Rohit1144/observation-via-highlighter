"""Ask the Highlighter agent a question.

    python -m agent.ask "Which sites had the most unresolved high-severity hazards last month?"
    python -m agent.ask -v "..."    # also print the code the agent ran and its output
"""

import argparse
import asyncio

from .relay import ask


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the Highlighter agent a question.")
    parser.add_argument("question")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="print Code Interpreter code and output as they happen")
    args = parser.parse_args()
    asyncio.run(ask(args.question, verbose=args.verbose))


if __name__ == "__main__":
    main()
