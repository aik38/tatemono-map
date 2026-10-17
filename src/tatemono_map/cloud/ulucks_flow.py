"""Browser-only Ulucks member-site PDF acquisition.

No endpoints or UI selectors are guessed. A reviewed flow JSON must describe the
actual member site's login and print screen. Smartlink is intentionally not used.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ALLOWED_ACTIONS = {"goto", "fill", "click", "select_label", "select_value", "check", "expect_visible"}
REQUIRED_KEYS = {"login_url", "steps", "pdf_trigger_selector", "pdf_capture"}
TOKENS = {"USER": "ULUCKS_USER", "PASSWORD": "ULUCKS_PASSWORD"}


class FlowError(RuntimeError):
    pass


def load_flow(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict) or not REQUIRED_KEYS.issubset(cfg):
        raise FlowError("Ulucks flow requires login_url, steps, pdf_trigger_selector, pdf_capture")
    if not str(cfg["login_url"]).startswith("https://") or "REPLACE_" in cfg["login_url"]:
        raise FlowError("Member-site login_url has not been verified")
    if cfg["pdf_capture"] not in ("download", "response"):
        raise FlowError("pdf_capture must be download or response (original PDF, not print-to-PDF)")
    if not isinstance(cfg["steps"], list) or not cfg["steps"]:
        raise FlowError("No verified UI steps")
    if any(step.get("action") not in ALLOWED_ACTIONS for step in cfg["steps"]):
        raise FlowError("Unsupported UI action")
    if not cfg["pdf_trigger_selector"] or "REPLACE_" in cfg["pdf_trigger_selector"]:
        raise FlowError("PDF trigger selector is not verified")
    for step in cfg["steps"]:
        if step["action"] != "goto" and (not step.get("selector") or "REPLACE_" in step["selector"]):
            raise FlowError("Unverified UI selector")
    return cfg


def resolve(value: str, company: str, area: str) -> str:
    allowed = {"COMPANY": company, "AREA": area}
    for key, env_name in TOKENS.items():
        allowed[key] = os.environ.get(env_name, "")
    result = str(value)
    for key, replacement in allowed.items():
        result = result.replace("{{" + key + "}}", replacement)
    if "{{" in result or "}}" in result:
        raise FlowError("Unknown template variable")
    return result


def _execute_step(page, step: dict, company: str, area: str) -> None:
    action = step["action"]
    if action == "goto":
        target = resolve(step.get("url", ""), company, area)
        if not target.startswith("https://"):
            raise FlowError("Invalid navigation URL")
        page.goto(target, wait_until="domcontentloaded")
        return
    locator = page.locator(resolve(step["selector"], company, area))
    if action == "fill":
        locator.fill(resolve(step.get("value", ""), company, area))
    elif action == "click":
        locator.click()
    elif action == "select_label":
        locator.select_option(label=resolve(step.get("value", ""), company, area))
    elif action == "select_value":
        locator.select_option(value=resolve(step.get("value", ""), company, area))
    elif action == "check":
        locator.check()
    elif action == "expect_visible":
        locator.wait_for(state="visible")


def fetch_original_pdf(flow: dict, company: str, area: str, destination: Path) -> Path:
    """Acquire the server-generated PDF. Never synthesize one with page.pdf()."""
    from playwright.sync_api import sync_playwright

    if not os.environ.get("ULUCKS_USER") or not os.environ.get("ULUCKS_PASSWORD"):
        raise FlowError("Ulucks login secrets not configured")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            page.goto(flow["login_url"], wait_until="domcontentloaded")
            for step in flow["steps"]:
                _execute_step(page, step, company, area)
            trigger = page.locator(resolve(flow["pdf_trigger_selector"], company, area))
            if flow["pdf_capture"] == "download":
                with page.expect_download(timeout=60000) as pending:
                    trigger.click()
                download = pending.value
                if download.failure():
                    raise FlowError("Server PDF download failed")
                download.save_as(str(destination))
            else:
                # Used when the member site returns application/pdf inline.
                predicate = lambda r: "application/pdf" in r.headers.get("content-type", "").lower()
                with page.expect_response(predicate, timeout=60000) as pending:
                    trigger.click()
                response = pending.value
                if not response.ok:
                    raise FlowError("Server PDF response failed")
                destination.write_bytes(response.body())
            context.close()
        finally:
            browser.close()
    if destination.stat().st_size < 100 or destination.open("rb").read(5) != b"%PDF-":
        destination.unlink(missing_ok=True)
        raise FlowError("The downloaded content is not a valid PDF header")
    return destination
