import os
import sys


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python build_release_notes.py <version> <output_path>")
        return 1

    version = sys.argv[1].strip()
    output_path = sys.argv[2]
    notes_path = os.path.join("release-notes", f"v{version}.md")

    if not os.path.exists(notes_path):
        raise FileNotFoundError(f"发布说明文件不存在: {notes_path}")

    with open(notes_path, "r", encoding="utf-8") as f:
        notes = f.read().strip()

    if not notes:
        raise RuntimeError(f"发布说明文件为空: {notes_path}")

    body = f"# SeaweedFSBrowser v{version}\n\n{notes}\n"
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
