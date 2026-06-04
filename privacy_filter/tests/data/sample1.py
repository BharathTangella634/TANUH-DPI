from PIL import Image, ImageDraw, ImageFont

# Create blank image
img = Image.new(
    "RGB",
    (700, 300),
    "white",
)

draw = ImageDraw.Draw(img)

# Optional: nicer font
try:
    font = ImageFont.truetype(
        "DejaVuSans.ttf",
        24,
    )
except:
    font = None

# Line 1 — Patient name
draw.text(

    (20,40),

    "PATIENT: JOHN DOE",

    fill="black",

    font=font,
)

# Line 2 — DOB
draw.text(

    (20,90),

    "DOB: 1990-01-01",

    fill="black",

    font=font,
)

# Line 3 — Multiple identifiers
draw.text(

    (20,140),

    "MRN: 123456789  ID: ABC987654",

    fill="black",

    font=font,
)

# Line 4 — Physician + hospital
draw.text(

    (20,190),

    "PHYSICIAN: DR JANE SMITH",

    fill="black",

    font=font,
)

# Line 5 — Study / accession
draw.text(

    (20,240),

    "ACCESSION: 20240528001",

    fill="black",

    font=font,
)

img.save(
    "sample.png"
)

print(
    "Saved -> sample.png"
)