"""Word/ODF specifics for `office_doc` uploads (.docx, .odt, legacy .doc); the
tools are in `write_documents`, the flow in `_local_document`. ICS detects the
format from the content, so the client only checks for a ZIP (docx, odt) or
OLE compound file (doc)."""

from __future__ import annotations

from ics_mcp.tools._local_document import DocumentSpec, document_hints

_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_RESAVE = "open it in Word or LibreOffice and save it as .docx (especially a legacy .doc)"

OFFICE = DocumentSpec(
    kind="office_doc",
    label="Word/ODF document",
    create_endpoint="/api/assets/document",
    mimes={
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".odt": "application/vnd.oasis.opendocument.text",
        ".doc": "application/msword",
    },
    has_signature=lambda raw: raw.startswith((_ZIP_MAGIC, _OLE_MAGIC)),
    signature_problem="no ZIP or OLE signature",
    extension_code="office_file_required",
    signature_code="invalid_office_document",
    hints={
        "office_file_required": "Upload a single .docx, .odt or .doc file.",
        "invalid_office_document": (
            f"The file is damaged or not a Word/ODF text document: {_RESAVE}. "
            "Spreadsheets and presentations are not supported."
        ),
        "office_encrypted": (
            "The document is password protected. Save an unprotected copy "
            "(remove the password in Word or LibreOffice) and upload that."
        ),
        "office_conversion_failed": (
            f"ICS could not convert the document. Retry once; if it fails again, {_RESAVE}."
        ),
        "office_too_large": (
            "The document exceeds the ICS cap (50 MB, or it unpacks to too much data). "
            "Remove or compress large images and embedded objects, or split it."
        ),
    },
)


OFFICE_HINTS = document_hints(OFFICE)
