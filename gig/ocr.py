"""Create searchable PDFs from ordered camera JPEGs using local tools."""
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

MAX_PAGES = 20


def searchable_pdf(pages):
    with TemporaryDirectory(prefix='gig-ocr-') as directory:
        workspace = Path(directory)
        documents = []
        for index, page in enumerate(pages, 1):
            image = workspace / f'page-{index}.jpg'
            output = image.with_suffix('')
            image.write_bytes(page)
            subprocess.run(
                ['tesseract', str(image), str(output), '-l', 'eng', '--dpi', '150', '--psm', '6', 'pdf'],
                check=True, capture_output=True, timeout=20,
            )
            documents.append(str(output.with_suffix('.pdf')))

        result = workspace / 'scan.pdf'
        subprocess.run(
            ['qpdf', '--empty', '--pages', *documents, '--', str(result)],
            check=True, capture_output=True, timeout=20,
        )
        return result.read_bytes()
