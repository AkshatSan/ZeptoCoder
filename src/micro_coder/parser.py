import re
from dataclasses import dataclass


@dataclass
class EditBlock:
    """Represents a single atomic edit operation on a target file."""
    filepath: str
    search_text: str
    replace_text: str


def parse_edit_blocks(response: str) -> list[EditBlock]:
    """
    Parses Aider-style SEARCH/REPLACE blocks from LLM responses.

    Expected format:
        path/to/file.py
        <<<<<<< SEARCH
        existing code
        =======
        replacement code
        >>>>>>> REPLACE
    """
    # Regex pattern:
    # 1. filepath on its own line (allows optional markdown ticks/headers)
    # 2. <<<<<<< SEARCH (5 to 9 angle brackets)
    # 3. search block
    # 4. ======= (5 to 9 equal signs)
    # 5. replace block
    # 6. >>>>>>> REPLACE (5 to 9 angle brackets)
    pattern = re.compile(
        r"(?:^|\n)"
        r"(?P<filepath>[^\n\r]+?)\s*\n"
        r"<{5,9}\s*SEARCH\s*\n"
        r"(?P<search>[\s\S]*?)\n"
        r"={5,9}\s*\n"
        r"(?P<replace>[\s\S]*?)\n"
        r">{5,9}\s*REPLACE",
        re.MULTILINE,
    )

    blocks: list[EditBlock] = []

    for match in pattern.finditer(response):
        raw_path = match.group("filepath").strip()

        # Clean markdown formatting: backticks (`path`), markdown headers (### path), bold (**path**)
        cleaned_path = raw_path.strip("`*# \t")

        # Strip markdown code fence markers if present on the line (e.g. ```python path/to/file.py)
        if cleaned_path.startswith("```"):
            cleaned_path = cleaned_path.lstrip("`").strip()
            tokens = cleaned_path.split()
            if tokens:
                cleaned_path = tokens[-1]

        search = match.group("search")
        replace = match.group("replace")

        blocks.append(
            EditBlock(
                filepath=cleaned_path,
                search_text=search,
                replace_text=replace,
            )
        )

    return blocks


if __name__ == "__main__":
    # Test sample with simulated LLM response text (including conversational text & multiple blocks)
    sample_response = """
Here are the changes requested:

1. Update the greeting function:
`src/micro_coder/greeting.py`
def greet(name: str = "micro-coder"):
    print(f"hello {name}!")

2. Also update the CLI call site:
### src/micro_coder/main.py
greet("developer")
"""

    parsed = parse_edit_blocks(sample_response)
    print(f"Parsed {len(parsed)} edit block(s):\n")

    for idx, b in enumerate(parsed, 1):
        print(f"--- Block {idx} ---")
        print(f"Target File : {b.filepath}")
        print(f"SEARCH      :\n{b.search_text}")
        print(f"REPLACE     :\n{b.replace_text}\n")