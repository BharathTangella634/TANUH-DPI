from privacy_filter.loaders.dicom import (
    DicomLoader,
)

from privacy_filter.loaders.image import (
    ImageLoader,
)

from privacy_filter.loaders.nifti import (
    NiftiLoader,
)

from privacy_filter.loaders.pdf import (
    PDFLoader,
)


def test_dicom_loader(
    sample_dicom,
):

    loader = DicomLoader()

    artifact = loader.load(
        sample_dicom
    )

    assert artifact is not None

    assert artifact.image is not None


def test_image_loader(
    sample_png,
):

    loader = ImageLoader()

    artifact = loader.load(
        sample_png
    )

    assert artifact.image is not None


def test_nifti_loader(
    sample_nifti,
):

    loader = NiftiLoader()

    artifact = loader.load(
        sample_nifti
    )

    assert artifact.image is not None


def test_pdf_loader(
    sample_pdf,
):

    loader = PDFLoader()

    artifact = loader.load(
        sample_pdf
    )

    assert artifact.image is not None