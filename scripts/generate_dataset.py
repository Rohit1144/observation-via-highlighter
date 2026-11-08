"""Generate the mock Highlighter dataset into data/.

Writes sites.json, observations.jsonl and metadata.json. Deterministic: the same
seed always produces byte-identical files. The logic lives in scripts/datagen/.

Usage:  python scripts/generate_dataset.py
"""

import json

from datagen import generate
from datagen.config import OUT_DIR


def main() -> None:
    sites, observations, metadata = generate()
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "sites.json").write_text(json.dumps(sites, indent=2) + "\n")
    (OUT_DIR / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    with open(OUT_DIR / "observations.jsonl", "w") as f:
        for o in observations:
            f.write(json.dumps(o, separators=(",", ":")) + "\n")
    print(f"wrote {len(sites)} sites, {len(observations)} observations to {OUT_DIR}")


if __name__ == "__main__":
    main()
