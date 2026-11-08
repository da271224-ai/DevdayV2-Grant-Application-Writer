"""Small injectable adapter for schema-constrained Responses API calls."""

import json
import re


class StructuredResponseError(RuntimeError):
    """The API did not return a usable structured result."""

    def __init__(self, message: str, code: str = "invalid_response", *, request_id=None, status=None):
        diagnostics = []
        if isinstance(status, int) and 100 <= status <= 599:
            diagnostics.append(f"HTTP {status}")
        if isinstance(request_id, str) and re.fullmatch(r"req_[A-Za-z0-9_-]{1,100}", request_id):
            diagnostics.append(f"request_id={request_id}")
        super().__init__(f"{message} ({', '.join(diagnostics)})" if diagnostics else message)
        self.code = code


def classify_api_error(error: Exception) -> StructuredResponseError:
    status = getattr(error, "status_code", None)
    api_code = getattr(error, "code", None)
    if api_code in ("insufficient_quota", "billing_hard_limit_reached"):
        code = "quota"
    elif status == 429:
        code = "rate_limit"
    elif isinstance(error, TimeoutError) or type(error).__name__ == "APITimeoutError" or status == 408:
        code = "timeout"
    elif status in (401, 403):
        code = "authentication"
    elif isinstance(status, int) and 500 <= status <= 599:
        code = "server_error"
    elif status in (400, 404, 409, 422):
        code = "invalid_request"
    elif type(error).__name__ == "APIResponseValidationError":
        code = "invalid_response"
    else:
        code = "api_error"
    return StructuredResponseError("API request failed.", code, request_id=getattr(error, "request_id", None),
                                   status=status)


def object_schema(**properties):
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


STRING = {"type": "string"}


def array_schema(items):
    return {"type": "array", "items": items}


def matches_schema(value, schema):
    if schema["type"] == "object":
        properties = schema["properties"]
        return isinstance(value, dict) and value.keys() == properties.keys() and all(
            matches_schema(value[key], field) for key, field in properties.items()
        )
    if schema["type"] == "array":
        return isinstance(value, list) and all(matches_schema(item, schema["items"]) for item in value)
    return isinstance(value, str) and ("enum" not in schema or value in schema["enum"])


def request_json(client, model, name, schema, instructions, context):
    try:
        response = client.responses.create(
            model=model, store=False, instructions=instructions, input=json.dumps(context),
            text={"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}},
        )
    except Exception as error:
        # API exceptions may embed request data. Keep them out of reports.
        raise classify_api_error(error) from None
    request_id = getattr(response, "_request_id", None)
    if any(
        getattr(part, "type", None) == "refusal"
        for item in (getattr(response, "output", None) or ())
        for part in (getattr(item, "content", None) or ())
    ):
        raise StructuredResponseError("The model refused the request.", "refusal", request_id=request_id)
    if response.status == "incomplete":
        raise StructuredResponseError("The model response was incomplete.", "incomplete", request_id=request_id)
    if response.status != "completed":
        raise StructuredResponseError("The model response did not complete.", "response_failed", request_id=request_id)
    try:
        result = json.loads(response.output_text)
    except (ValueError, TypeError, AttributeError):
        raise StructuredResponseError("Response did not contain valid JSON.", request_id=request_id) from None
    if not matches_schema(result, schema):
        raise StructuredResponseError("Response did not match the requested schema.", request_id=request_id)
    return result

