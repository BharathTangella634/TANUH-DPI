from privacy_filter.metadata.dicom_cleaner import (
    DicomCleaner,
)

from privacy_filter.metadata.exif_cleaner import (
    EXIFCleaner,
)

from privacy_filter.metadata.nifti_cleaner import (
    NiftiCleaner,
)


def test_dicom_cleaner(
    sample_dicom,
    temp_output,
):

    cleaner = DicomCleaner()

    report = cleaner.clean_file(

        sample_dicom,

        temp_output/"clean.dcm",
    )

    assert report is not None


def test_exif_cleaner(
    sample_jpg,
    temp_output,
):

    cleaner = EXIFCleaner()

    report = cleaner.clean_file(

        sample_jpg,

        temp_output/"clean.jpg",
    )

    assert report.metadata_removed >= 0


def test_nifti_cleaner(
    sample_nifti,
    temp_output,
):

    cleaner = NiftiCleaner()

    report = cleaner.clean_file(

        sample_nifti,

        temp_output/"clean.nii.gz",
    )

    assert report is not None