from privacy_filter.loaders.image import (
    ImageLoader,
)

from privacy_filter.validators.validator import (
    Validator,
)


def test_validator(
    sample_png,
):

    loader = ImageLoader()

    artifact = loader.load(
        sample_png
    )

    validator = Validator(

        ocr_backend="tesseract"
    )

    result = validator.validate(
        artifact
    )

    assert result is not None