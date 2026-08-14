from .client import call_llm
from .prompts import build_system_prompt
from .validator import validate_llm_qasm_reply
import time
from .policy import get_case_timeout

MAX_ATTEMPTS = 3

def agent_chat_impl(
    prompt: str
) -> str:
    case_timeout = get_case_timeout()    
    start_time = time.monotonic()
    if not isinstance(prompt, str):
        raise TypeError(
            "prompt must be a string"
        )

    if not prompt.strip():
        raise ValueError(
            "prompt must not be empty"
        )

    system_prompt = build_system_prompt()

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    last_reply = ""

    for attempt in range(MAX_ATTEMPTS):
        elapsed = (
            time.monotonic()
            - start_time
        )
        
        remaining = (
            case_timeout
            - elapsed
        )
        request_timeout = (
            remaining - 5.0
        )  
        if request_timeout <= 0:
            break
        reply = call_llm(
            messages,
            timeout=request_timeout,
        )      

        last_reply = reply

        # Backend recommendation normally contains no QASM.
        if "OPENQASM" not in reply.upper():
            return reply

        validation = (
            validate_llm_qasm_reply(
                reply
            )
        )

        if validation["ok"]:
            return validation["qasm"]

        error = validation["error"]

        messages.append(
            {
                "role": "assistant",
                "content": reply,
            }
        )

        messages.append(
            {
                "role": "user",
                "content": (
                    "Your previous OpenQASM "
                    "failed LoomQ L1 validation.\n\n"
                    f"Validation error:\n"
                    f"{error}\n\n"
                    "Please fix the program while "
                    "preserving the original user "
                    "intent.\n"
                    "Return a complete OpenQASM 2.0 "
                    "program."
                ),
            }
        )

    return last_reply
