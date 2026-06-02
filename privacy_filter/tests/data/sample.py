from PIL import Image, ImageDraw

img = Image.new(
    "RGB",
    (500,200),
    "white",
)

draw = ImageDraw.Draw(img)

draw.text(

    (20,50),

    "PATIENT: JOHN DOE",

    fill="black",
)

img.save(
    "sample.png"
)