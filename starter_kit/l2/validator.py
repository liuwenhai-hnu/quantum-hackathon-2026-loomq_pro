import re
from typing import Any, Dict, Optional

from l1 import parse_qasm2
def extract_qasm_block(text: str) -> str:
    text = text.strip()

    fenced_match = re.search(
        r"```(?:qasm)?\s*(.*?)```",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if fenced_match:
        return fenced_match.group(1).strip()

    return text

def validate_qasm_text(
    qasm_text: str
) -> Dict[str, Any]:

    cleaned_qasm = qasm_text.strip()

    if not cleaned_qasm:
        return {
            "ok": False,
            "qasm": "",
            "error": "Empty QASM output.",
        }

    try:
        circuit = parse_qasm2(cleaned_qasm)

    except Exception as exc:
        return {
            "ok": False,
            "qasm": cleaned_qasm,
            "error": str(exc),
        }

    return {
        "ok": True,
        "qasm": cleaned_qasm,
        "error": None,
        "circuit": circuit,
    }
def validate_llm_qasm_reply(
    reply_text: str
) -> Dict[str, Any]:

    extracted_qasm = extract_qasm_block(
        reply_text
    )

    result = validate_qasm_text(
        extracted_qasm
    )

    result["raw_reply"] = reply_text

    return result
