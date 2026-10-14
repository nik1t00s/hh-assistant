"""Local OpenAI-compatible endpoint diagnostics. Python stdlib only."""
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_config(config):
    url = urlsplit(config["base_url"])
    if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1", "localhost"}
            or url.username or url.password or url.query or url.fragment
            or url.path.rstrip("/") != "/v1"):
        raise ValueError("base_url must be local HTTP ending in /v1")
    if not isinstance(config["model"], str) or not config["model"].strip():
        raise ValueError("model must be a nonempty exact API model ID")
    for field in ("timeout_seconds", "max_tokens"):
        if type(config[field]) is not int or config[field] <= 0:
            raise ValueError(field + " must be a positive integer")
    return config


def request(config, path, payload=None):
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("LOCAL_LLM_API_KEY")
    if key:
        headers["Authorization"] = "Bearer " + key
    req = Request(config["base_url"].rstrip("/") + path,
                  data=None if payload is None else json.dumps(payload).encode("utf-8"),
                  headers=headers)
    # Do not send local requests through a corporate proxy or follow redirects.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(req, timeout=config["timeout_seconds"]) as response:
        return json.load(response)


def validate_tool_call(message):
    calls = message.get("tool_calls") or []
    if len(calls) != 1:
        raise ValueError("Expected one structured tool call, got " + str(len(calls)))
    call = calls[0]
    function = call.get("function", {})
    if (call.get("type") != "function" or not call.get("id")
            or function.get("name") != "echo_probe"
            or json.loads(function.get("arguments", "null")) != {"text": "LOCAL_AGENT_OK"}):
        raise ValueError("Tool name, ID or arguments did not match the probe")
    return call


def smoke(config, tools=False):
    messages = [{"role": "system", "content": "Follow the user's instruction precisely."},
                {"role": "user", "content": "Reply with exactly LOCAL_AGENT_OK."}]
    payload = {"model": config["model"], "messages": messages,
               "temperature": 0, "max_tokens": config["max_tokens"], "stream": False}
    if tools:
        messages[1]["content"] = 'Call echo_probe once with text="LOCAL_AGENT_OK". Do not answer in prose.'
        payload["tools"] = [{"type": "function", "function": {
            "name": "echo_probe", "description": "Echo a diagnostic string; no side effects.",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}},
                           "required": ["text"], "additionalProperties": False}}}]
        payload["tool_choice"] = "auto"
    message = request(config, "/chat/completions", payload)["choices"][0]["message"]
    if not tools:
        if (message.get("content") or "").strip() != "LOCAL_AGENT_OK":
            raise ValueError("Model did not return the expected text (possibly output budget exhausted)")
        print("PASS: text generation")
        return
    call = validate_tool_call(message)
    # The only tool result is a fixed string. Never execute model-supplied code.
    messages += [message, {"role": "tool", "tool_call_id": call["id"], "content": "LOCAL_AGENT_OK"},
                 {"role": "user", "content": "Reply with exactly the tool result, nothing else."}]
    payload.pop("tools")
    payload.pop("tool_choice")
    final = request(config, "/chat/completions", payload)["choices"][0]["message"]
    if (final.get("content") or "").strip() != "LOCAL_AGENT_OK":
        raise ValueError("Tool result round trip failed (possibly output budget exhausted)")
    print("PASS: structured tool call and result round trip; no shell or file access")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--smoke", action="store_true", help="Send a short generation request")
    parser.add_argument("--tools", action="store_true", help="Test structured tool calls and tool result")
    parser.add_argument("--offline", action="store_true", help="Validate config without any network request")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    config_path = args.config or (root / "config.local.json")
    if args.config is None and not config_path.exists():
        config_path = root / "config.example.json"
    try:
        config = validate_config(json.loads(config_path.read_text(encoding="utf-8-sig")))
        if args.offline:
            if args.smoke or args.tools:
                raise ValueError("--offline cannot be combined with generation checks")
            print("PASS: config; no network requests")
            return 0
        listing = request(config, "/models")
        ids = [entry["id"] for entry in listing["data"]]
        print("Endpoint reachable. Model IDs:")
        for model_id in ids:
            print("  " + model_id)
        if args.smoke or args.tools:
            if config["model"] not in ids:
                raise ValueError("Configured model not listed; copy exact ID into config.local.json")
            smoke(config, tools=args.tools)
        else:
            print("Discovery only. Listing does not prove model is loaded or tool use works.")
        return 0
    except HTTPError as exc:
        print(f"FAIL: HTTP {exc.code}; check server/auth/request compatibility", file=sys.stderr)
    except URLError:
        print("FAIL: endpoint unavailable; check LM Studio server and port", file=sys.stderr)
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        print("FAIL: " + str(exc), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
