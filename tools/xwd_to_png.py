#!/usr/bin/env python3
"""Convert an X11 ``xwd`` dump to PNG.

Why this exists: this machine has xwd but no ImageMagick, no netpbm and no
gnome-screenshot, so there is no way to turn a window capture into a viewable
image.  PIL is installed but cannot read xwd, so the format is parsed here.

It is a diagnostic tool.  Nothing in the collector imports it.

    xwd -display :0 -id <window> -out shot.xwd
    python3 tools/xwd_to_png.py shot.xwd shot.png
"""

import struct
import sys

from PIL import Image

# XWD file header: 25 or more big-endian 32-bit fields, then the window name,
# then (for a DirectColor/TrueColor visual) the colour map, then the raster.
_HEADER_FIELDS = (
    "header_size", "file_version", "pixmap_format", "pixmap_depth",
    "pixmap_width", "pixmap_height", "xoffset", "byte_order",
    "bitmap_unit", "bitmap_bit_order", "bitmap_pad", "bits_per_pixel",
    "bytes_per_line", "visual_class", "red_mask", "green_mask", "blue_mask",
    "bits_per_rgb", "colormap_entries", "ncolors", "window_width",
    "window_height", "window_x", "window_y", "window_bdrwidth",
)


def read_header(data):
    values = struct.unpack(">%dI" % len(_HEADER_FIELDS),
                           data[:4 * len(_HEADER_FIELDS)])
    header = dict(zip(_HEADER_FIELDS, values))
    if header["file_version"] != 7:
        raise ValueError("not an xwd v7 file (version=%s)"
                         % header["file_version"])
    return header


def mask_shift(mask):
    """(shift, width) for a colour mask, e.g. 0x00ff0000 -> (16, 8)."""
    if not mask:
        return 0, 0
    shift = 0
    while not (mask >> shift) & 1:
        shift += 1
    width = 0
    while (mask >> (shift + width)) & 1:
        width += 1
    return shift, width


def convert(xwd_path, png_path, max_width=None):
    with open(xwd_path, "rb") as handle:
        data = handle.read()

    header = read_header(data)
    width = header["pixmap_width"]
    height = header["pixmap_height"]
    bpp = header["bits_per_pixel"]
    stride = header["bytes_per_line"]

    if bpp not in (24, 32):
        raise ValueError("only 24/32 bits-per-pixel are handled, got %d" % bpp)

    # The raster begins after the header and the colour map.
    offset = header["header_size"] + header["ncolors"] * 12

    red_shift, _ = mask_shift(header["red_mask"])
    green_shift, _ = mask_shift(header["green_mask"])
    blue_shift, _ = mask_shift(header["blue_mask"])
    big_endian = header["byte_order"] == 1
    pixel_bytes = bpp // 8

    image = Image.new("RGB", (width, height))
    pixels = image.load()

    for y in range(height):
        row = offset + y * stride
        for x in range(width):
            start = row + x * pixel_bytes
            chunk = data[start:start + pixel_bytes]
            if len(chunk) < pixel_bytes:
                continue
            if pixel_bytes == 4:
                value = struct.unpack(">I" if big_endian else "<I", chunk)[0]
            else:
                value = (int.from_bytes(chunk, "big" if big_endian else "little"))
            pixels[x, y] = (
                (value >> red_shift) & 0xFF,
                (value >> green_shift) & 0xFF,
                (value >> blue_shift) & 0xFF,
            )

    if max_width and image.width > max_width:
        ratio = max_width / float(image.width)
        image = image.resize((max_width, int(image.height * ratio)),
                             Image.LANCZOS)

    image.save(png_path, "PNG", optimize=True)
    return image.size


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: xwd_to_png.py INPUT.xwd OUTPUT.png [MAX_WIDTH]")
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else None
    size = convert(sys.argv[1], sys.argv[2], limit)
    print("wrote %s %dx%d" % (sys.argv[2], size[0], size[1]))
