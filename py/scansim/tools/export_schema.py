"""Write the JSON schemas and a sample snapshot for the client: python -m scansim.tools.export_schema OUT_DIR"""
import json
import sys
from pathlib import Path

from pydantic import TypeAdapter

from scansim.actions import Action
from scansim.examples import sample_snapshot
from scansim.snapshot import Snapshot


def export(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "snapshot.schema.json": Snapshot.model_json_schema(),
        "actions.schema.json": TypeAdapter(Action).json_schema(),
        "snapshot.sample.json": sample_snapshot().model_dump(mode="json"),
    }
    paths = []
    for name, content in files.items():
        path = out_dir / name
        path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: python -m scansim.tools.export_schema OUT_DIR\n")
        return 2
    export(Path(argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
