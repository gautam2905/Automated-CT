from pathlib import Path

from scansim.protocols.schema import CTProtocol


def load_protocol(path: Path) -> CTProtocol:
    return CTProtocol.model_validate_json(Path(path).read_text(encoding="utf-8"))


def load_library(data_dir: Path) -> dict[str, CTProtocol]:
    protocols = (load_protocol(p) for p in sorted((Path(data_dir) / "protocols" / "ct").glob("*.json")))
    return {p.id: p for p in protocols}
