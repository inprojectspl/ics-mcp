"""What is specific to PDF uploads (`pdf_doc`): extensions, signature check
and the ICS error codes with their fix hints. The tools are in
`write_documents`, the upload flow in `_local_document`.
"""

from __future__ import annotations

from ics_mcp.tools._local_document import DocumentSpec, document_hints

# The PDF spec tolerates junk before the header; readers look within the
# first 1024 bytes, so the client check does the same. ICS stays the
# authority (it also parses the file).
_SIGNATURE_WINDOW = 1024

PDF = DocumentSpec(
    kind="pdf_doc",
    label="PDF",
    create_endpoint="/api/assets/pdf",
    mimes={".pdf": "application/pdf"},
    has_signature=lambda raw: b"%PDF-" in raw[:_SIGNATURE_WINDOW],
    signature_problem="no %PDF- signature",
    extension_code="pdf_file_required",
    signature_code="invalid_pdf",
    hints={
        "pdf_file_required": "Upload a single file with the .pdf extension.",
        "invalid_pdf": "The file is damaged or not a PDF. Re-export or re-save it as PDF.",
        "pdf_encrypted": (
            "The PDF is password protected. Save an unprotected copy "
            "(e.g. `qpdf --decrypt in.pdf out.pdf`) and upload that."
        ),
        "pdf_extraction_failed": (
            "ICS could not extract the text in time. Retry once; if it fails again, "
            "re-save the PDF (print to PDF) or split it."
        ),
        "pdf_too_large": (
            "The PDF exceeds the ICS per-file cap (default 50 MB). Compress or split it."
        ),
    },
)


PDF_HINTS = document_hints(PDF)
