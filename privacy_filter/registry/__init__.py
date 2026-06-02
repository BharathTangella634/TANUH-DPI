"""
Registry bootstrap.
"""

from ..schemas.core import (
    FileFormat,
)

from ..registry.loader_registry import (
    LoaderRegistry,
)

from ..registry.cleaner_registry import (
    CleanerRegistry,
)

from ..registry.redactor_registry import (
    RedactorRegistry,
)

from ..registry.saver_registry import (
    SaverRegistry,
)

# -------- loaders --------

from ..loaders.dicom import (
    DicomLoader,
)

from ..loaders.image import (
    ImageLoader,
)

from ..loaders.nifti import (
    NiftiLoader,
)

from ..loaders.pdf import (
    PDFLoader,
)

LoaderRegistry.register(
    DicomLoader()
)

LoaderRegistry.register(
    NiftiLoader()
)

LoaderRegistry.register(
    PDFLoader()
)

LoaderRegistry.register(
    ImageLoader()
)

# -------- cleaners --------

from ..metadata.dicom_cleaner import (
    DicomCleaner,
)

from ..metadata.exif_cleaner import (
    EXIFCleaner,
)

from ..metadata.nifti_cleaner import (
    NiftiCleaner,
)

CleanerRegistry.register(

    FileFormat.DICOM,

    DicomCleaner(),
)

CleanerRegistry.register(

    FileFormat.NIFTI,

    NiftiCleaner(),
)

CleanerRegistry.register(

    FileFormat.PNG,

    EXIFCleaner(),
)

CleanerRegistry.register(

    FileFormat.JPG,

    EXIFCleaner(),
)

CleanerRegistry.register(

    FileFormat.JPEG,

    EXIFCleaner(),
)

CleanerRegistry.register(

    FileFormat.TIFF,

    EXIFCleaner(),
)

CleanerRegistry.register(

    FileFormat.BMP,

    EXIFCleaner(),
)

# -------- redactors --------

from ..redactors.mask import (
    MaskRedactor,
)

from ..redactors.crop import (
    CropRedactor,
)

from ..redactors.inpaint import (
    InpaintRedactor,
)

RedactorRegistry.register(

    "mask",

    MaskRedactor(),
)

RedactorRegistry.register(

    "crop",

    CropRedactor(),
)

RedactorRegistry.register(

    "inpaint",

    InpaintRedactor(),
)

# -------- savers --------

from ..savers.image_saver import (
    ImageSaver,
)

from ..savers.dicom_saver import (
    DicomSaver,
)

from ..savers.nifti_saver import (
    NiftiSaver,
)

from ..savers.pdf_saver import (
    PDFSaver,
)

SaverRegistry.register(

    FileFormat.DICOM,

    DicomSaver(),
)

SaverRegistry.register(

    FileFormat.NIFTI,

    NiftiSaver(),
)

SaverRegistry.register(

    FileFormat.PDF,

    PDFSaver(),
)

SaverRegistry.register(

    FileFormat.PNG,

    ImageSaver(),
)

SaverRegistry.register(

    FileFormat.JPG,

    ImageSaver(),
)

SaverRegistry.register(

    FileFormat.JPEG,

    ImageSaver(),
)

SaverRegistry.register(

    FileFormat.TIFF,

    ImageSaver(),
)

SaverRegistry.register(

    FileFormat.BMP,

    ImageSaver(),
)