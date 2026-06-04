from privacy_filter.loaders.image import (
    ImageLoader,
)

from privacy_filter.redactors.mask import (
    MaskRedactor,
)

from privacy_filter.redactors.crop import (
    CropRedactor,
)

from privacy_filter.redactors.inpaint import (
    InpaintRedactor,
)

from privacy_filter.schemas.core import (
    PHIEntity,
    PHISource,
    BoundingBox,
)


def fake_entity():

    return PHIEntity(

        label="TEST",

        confidence=1.0,

        source=PHISource.RULE,

        text="JOHN DOE",

        bbox=BoundingBox(

            x1=10,
            y1=10,

            x2=100,
            y2=50,
        ),
    )


def test_mask_redactor(
    sample_png,
):

    loader = ImageLoader()

    artifact = loader.load(
        sample_png
    )

    redactor = MaskRedactor()

    artifact, report = redactor.redact(

        artifact,

        [fake_entity()],
    )

    assert report is not None


def test_crop_redactor(
    sample_png,
):

    loader = ImageLoader()

    artifact = loader.load(
        sample_png
    )

    redactor = CropRedactor()

    artifact, report = redactor.redact(

        artifact,

        [fake_entity()],
    )

    assert artifact.image is not None


def test_inpaint_redactor(
    sample_png,
):

    loader = ImageLoader()

    artifact = loader.load(
        sample_png
    )

    redactor = InpaintRedactor()

    artifact, report = redactor.redact(

        artifact,

        [fake_entity()],
    )

    assert report is not None