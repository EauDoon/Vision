"""Build a static copy of the replay comparison and evidence atlas in a new directory."""
import argparse
from contextlib import ExitStack
from pathlib import Path

from replay_compare import packet_bytes


ROOT = Path(__file__).resolve().parent
ASSET_DIR = ROOT / "static" / "replay"
ARCHIVE_LICENSE = ROOT / "fixtures" / "balancer-vault" / "LICENSE"
ASSETS = ("index.html", "review.js", "style.css", "atlas.html", "atlas.js", "atlas.css")


def publish(output):
    """Publish the public report assets, upstream notice and API packet bytes."""
    files = {name: (ASSET_DIR / name).read_bytes() for name in ASSETS}
    files["packet.json"] = packet_bytes()
    files["archive-LICENSE.txt"] = ARCHIVE_LICENSE.read_bytes()
    # Reserve the destination exclusively. On a short write, clean up only files
    # created by this invocation so the caller can retry the same command.
    with ExitStack() as rollback:
        output.mkdir()
        rollback.callback(output.rmdir)
        for name, content in files.items():
            path = output / name
            with path.open("xb") as writer:
                rollback.callback(path.unlink)
                writer.write(content)
        rollback.pop_all()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, metavar="NEW_DIR",
                        help="new directory inside an existing parent directory")
    args = parser.parse_args()
    try:
        publish(args.output)
    except FileExistsError:
        parser.exit(1, f"Output already exists. Choose a new directory: {args.output}\n")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Could not build static report: {exc}\n")
    print(f"Built static report in {args.output}")


if __name__ == "__main__":
    main()
