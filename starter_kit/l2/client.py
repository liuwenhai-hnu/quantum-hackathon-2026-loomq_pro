import json
import os
import urllib.error
import urllib.request
from .policy import (
    get_temperature,
    get_stream,
    get_thinking,
)

def get_llm_config():
    base_url = os.environ.get(
        "LOOMQ_LLM_BASE_URL"
    )

    api_key = os.environ.get(
        "LOOMQ_LLM_API_KEY"
    )

    model = os.environ.get(
        "LOOMQ_LLM_MODEL"
    )

    if not base_url:
        raise RuntimeError(
            "LOOMQ_LLM_BASE_URL is not set"
        )

    if not api_key:
        raise RuntimeError(
            "LOOMQ_LLM_API_KEY is not set"
        )

    if not model:
        raise RuntimeError(
            "LOOMQ_LLM_MODEL is not set"
        )

    return (
        base_url,
        api_key,
        model,
    )

def build_chat_endpoint(
    base_url: str
) -> str:

    base_url = base_url.rstrip("/")

    if base_url.endswith(
        "/chat/completions"
    ):
        return base_url

    return (
        base_url
        + "/chat/completions"
    )
    
def call_llm(
    messages: list,
    timeout:float,
) -> str:

    (
        base_url,
        api_key,
        model,
    ) = get_llm_config()

    endpoint = build_chat_endpoint(
        base_url
    )

    payload = {
        "model": model,
        "messages": messages,
        "temperature": get_temperature(),
        "stream": get_stream(),
        "thinking": get_thinking(),
    }
    data = json.dumps(
        payload
    ).encode("utf-8")

    request = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "Content-Type":
                "application/json",

            "Authorization":
                f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:

            body = response.read()

    except urllib.error.HTTPError as exc:

        error_body = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        raise RuntimeError(
            f"LLM HTTP error "
            f"{exc.code}: "
            f"{error_body}"
        ) from exc

    except urllib.error.URLError as exc:

        raise RuntimeError(
            f"LLM connection error: "
            f"{exc}"
        ) from exc

    result = json.loads(
        body.decode("utf-8")
    )

    try:
        content = (
            result["choices"][0]
            ["message"]["content"]
        )

    except (
        KeyError,
        IndexError,
        TypeError,
    ) as exc:

        raise RuntimeError(
            "Invalid LLM response format"
        ) from exc

    return content
