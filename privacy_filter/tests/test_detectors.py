from privacy_filter.loaders.image import (
    ImageLoader,
)

from privacy_filter.loaders.dicom import (
    DicomLoader,
)

from privacy_filter.detectors.metadata_detector import (
    MetadataDetector,
)

from privacy_filter.detectors.overlay_detector import (
    OverlayDetector,
)

from privacy_filter.detectors.ocr_detector import (
    OCRDetector,
)

from privacy_filter.detectors.phi_detector import (
    PHIDetector,
)


def test_metadata_detector(
    sample_dicom,
):

    loader = DicomLoader()

    artifact = loader.load(
        sample_dicom
    )

    detector = MetadataDetector()

    result = detector.detect(
        artifact
    )

    assert isinstance(
        result,
        list,
    )


def test_overlay_detector(
    sample_png,
):

    loader = ImageLoader()

    artifact = loader.load(
        sample_png
    )

    detector = OverlayDetector()

    regions = detector.detect(
        artifact
    )

    assert isinstance(
        regions,
        list,
    )


def test_ocr_detector(
    sample_png,
):

    loader = ImageLoader()

    artifact = loader.load(
        sample_png
    )

    detector = OCRDetector(
        backend="tesseract"
    )

    result = detector.detect(
        artifact
    )

    assert isinstance(
        result,
        list,
    )


def test_phi_detector():

    detector = PHIDetector()

    assert detector is not None