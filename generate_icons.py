import zlib
import struct
from pathlib import Path

def create_cricket_icon(size: int, output_path: Path):
    # Create simple RGBA image buffer: Emerald background with a golden cricket ball in the center
    width = size
    height = size
    raw_data = bytearray()

    cx, cy = width // 2, height // 2
    r_radius = width // 3

    for y in range(height):
        raw_data.append(0)  # filter type None
        for x in range(width):
            dist_sq = (x - cx) ** 2 + (y - cy) ** 2
            if dist_sq < (r_radius ** 2):
                # Golden Cricket Ball
                raw_data.extend([234, 179, 8, 255])
            elif dist_sq < ((r_radius + 4) ** 2):
                # Seam / Border
                raw_data.extend([255, 255, 255, 255])
            else:
                # Emerald Background with slight gradient
                val = int(16 + (y / height) * 20)
                raw_data.extend([5, val + 100, 70, 255])

    def png_chunk(chunk_type, data):
        return (
            struct.pack(">I", len(data))
            + chunk_type
            + data
            + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
        )

    png_header = b"\x89PNG\r\n\x1a\n"
    ihdr = png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    compressed = zlib.compress(bytes(raw_data), 9)
    idat = png_chunk(b"IDAT", compressed)
    iend = png_chunk(b"IEND", b"")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(png_header + ihdr + idat + iend)

if __name__ == "__main__":
    icon_dir = Path(__file__).resolve().parent / "app" / "static" / "icons"
    create_cricket_icon(192, icon_dir / "icon-192.png")
    create_cricket_icon(512, icon_dir / "icon-512.png")
    print("Icons generated successfully!")
