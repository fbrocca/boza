"""Write icons/favicon.ico: the brand mark (icons/favicon.svg) drawn on the pixel grid at 16, 32
and 48 px, so its lines stay sharp in browser tabs. Run with tools/make_icons.js when the mark changes."""
from PIL import Image, ImageDraw


def draw(n):
    # frame 6..58 of 64, stroke 4, dividers centred, bottom-right lot in marsh
    s = n / 64
    a, b, w = round(6 * s), round(58 * s), max(1, round(4 * s))
    mid = (a + b - w) // 2
    im = Image.new("RGB", (n, n), "#f5f2ea")
    d = ImageDraw.Draw(im)
    d.rectangle([mid + w, mid + w, b - w - 1, b - w - 1], fill="#2e5b3f")
    for r in ([a, a, b - 1, a + w - 1], [a, b - w, b - 1, b - 1], [a, a, a + w - 1, b - 1],
              [b - w, a, b - 1, b - 1], [a, mid, b - 1, mid + w - 1], [mid, a, mid + w - 1, b - 1]):
        d.rectangle(r, fill="#191b18")
    return im


if __name__ == "__main__":
    ims = {n: draw(n) for n in (16, 32, 48)}
    ims[48].save("icons/favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)], append_images=[ims[16], ims[32]])
