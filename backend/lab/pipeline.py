import os
from tempfile import NamedTemporaryFile

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_docling import DoclingLoader
from langchain_ollama import ChatOllama

from .schemas import LabReport

parser = PydanticOutputParser(pydantic_object=LabReport)

EXTRACTION_PROMPT = """You are a deterministic clinical laboratory data extraction engine.
Your sole job is to parse unstructured medical lab text into structured data.

### CRITICAL RULES:
1. Extract 'name', 'age_years' (ONLY the numerical integer, e.g., convert "28 YRS" to 28), 'sex', 'referred_by', and 'registration_no'.
2. 'report_date': Extract ONE date in 'DD/MM/YYYY' format. Strip any time values.
3. Ignore category headers like "PHYSICAL EXAMINATION", "CHEMICAL EXAMINATION", "HAEMATOLOGY". Do NOT make test entries for these.
4. Split merged rows (e.g., "SUGAR/GLUCOSE KETONE BODIES" -> Extract as two separate tests).
5. Extract all qualitative values (e.g., "Absent", "Pale Yellow") and quantitative values strictly.

{format_instructions}

Document Content:
{document}
"""


def _document_to_markdown(pdf_bytes: bytes) -> str:
    with NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
        pdf_file.write(pdf_bytes)
        pdf_path = pdf_file.name
    try:
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        loader = DoclingLoader(
            file_path=pdf_path, export_type="markdown", converter=converter
        )
        return "\n\n".join(document.page_content for document in loader.load())
    finally:
        os.unlink(pdf_path)


def extract_lab_report(pdf_bytes: bytes) -> LabReport:
    markdown = _document_to_markdown(pdf_bytes)
    if not markdown.strip():
        raise ValueError("Docling returned no readable text.")

    prompt = ChatPromptTemplate.from_template(
        EXTRACTION_PROMPT,
        partial_variables={"format_instructions": parser.get_format_instructions()},
    )
    model = ChatOllama(
        model=os.environ.get("PULSE_LAB_OLLAMA_MODEL", "llama3.1"),
        temperature=0,
        num_ctx=4096,
        format="json",
    )
    extractor = prompt | model | parser
    return extractor.invoke({"document": markdown})