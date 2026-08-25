import os
import re
from tempfile import NamedTemporaryFile

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_docling import DoclingLoader
from langchain_ollama import ChatOllama

from .schemas import LabReport, TestResult

# test_name pattern -> Layer 1's vitals key. Matched case-insensitively
# against whatever Docling/the LLM extracted, so "Pulse Rate", "PULSE", and
# "Heart Rate (HR)" all resolve to the same field regardless of how a given
# lab's template happens to word it.
_VITAL_PATTERNS: list[tuple[str, str]] = [
    (r"heart\s*rate|pulse", "heart_rate"),
    (r"resp(iratory)?\s*rate", "resp_rate"),
    (r"spo2|oxygen\s*sat(uration)?", "spo2"),
    (r"temp(erature)?", "temperature"),
    (r"blood\s*pressure|\bbp\b", "systolic_bp"),  # split further below
]


def infer_vitals(test_results: list[TestResult]) -> dict[str, float]:
    """Pull vital-sign readings out of the extracted test panel by name
    rather than by asking the LLM for a second, differently-shaped output —
    one extraction pass, one place that decides what counts as a vital, and
    a result that degrades to 'nothing found' instead of a malformed field
    if a report simply has no physical-exam block.
    """
    vitals: dict[str, float] = {}
    for test in test_results:
        name = test.test_name.lower()
        for pattern, key in _VITAL_PATTERNS:
            if not re.search(pattern, name):
                continue
            if key == "systolic_bp":
                # "120/80" is the one shape worth special-casing; anything
                # else under a "blood pressure" label is ambiguous and
                # dropped rather than guessed at.
                m = re.search(r"(\d{2,3})\s*/\s*(\d{2,3})", test.value)
                if m:
                    vitals["systolic_bp"] = float(m.group(1))
                    vitals["diastolic_bp"] = float(m.group(2))
                break
            m = re.search(r"-?\d+(\.\d+)?", test.value)
            if m:
                vitals[key] = float(m.group())
            break
    return vitals

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
    report = extractor.invoke({"document": markdown})
    report.vitals = infer_vitals(report.test_results)
    return report