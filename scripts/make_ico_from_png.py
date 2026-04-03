import struct
import sys


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def read_png_size(png_data: bytes) -> tuple[int, int]:
    if len(png_data) < 24 or png_data[:8] != PNG_SIGNATURE:
        raise ValueError("输入文件不是合法 PNG")
    width, height = struct.unpack(">II", png_data[16:24])
    return width, height


def write_ico_from_png(png_path: str, ico_path: str) -> None:
    with open(png_path, "rb") as f:
        png_data = f.read()

    width, height = read_png_size(png_data)
    width_byte = 0 if width >= 256 else width
    height_byte = 0 if height >= 256 else height

    icon_dir = struct.pack("<HHH", 0, 1, 1)
    icon_entry = struct.pack(
        "<BBBBHHII",
        width_byte,
        height_byte,
        0,
        0,
        1,
        32,
        len(png_data),
        6 + 16,
    )

    with open(ico_path, "wb") as f:
        f.write(icon_dir)
        f.write(icon_entry)
        f.write(png_data)


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python scripts/make_ico_from_png.py <input.png> <output.ico>")
        return 1
    write_ico_from_png(sys.argv[1], sys.argv[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
