"""Ulucks member UI automation based on the supplied 2026-10-16 screens.

No guessed PDF API: the print action is clicked and its actual authenticated
browser request is forwarded/captured. Screenshots, cookies and raw HTML are
never persisted. Login values are supplied by Secret Manager at runtime.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ORIGIN = "https://kitakyushu.ulucks.jp"
COMPANY_ID = "8"
COMPANY_LABEL = "株式会社不動産中央情報センター"
AREA_LABEL = "小倉北区"
PRINT_LABEL = re.compile(r"^[（(]新[）)]\s*エリア[・･]物件別で印刷$")


class CollectionError(RuntimeError):
    """Only fixed, non-sensitive error codes may reach shared logs."""


@dataclass
class Collected:
    pdfs: list[Path]
    expected_rows: int
    confirmed_zero: bool = False
    evidence: dict = field(default_factory=dict)


def normal(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def validate_config(config: dict) -> None:
    # First proof is deliberately limited to the user-specified company/area.
    if any(config.get(k) != v for k, v in {
        "login_url": ORIGIN + "/", "search_url": ORIGIN + "/company/lists/8",
        "company_id": COMPANY_ID, "company_label": COMPANY_LABEL,
        "area_id": "kokurakita", "area_label": AREA_LABEL,
        "address_contains": "小倉北区",
    }.items()):
        raise CollectionError("unsupported_collection_target")
    keys = config.get("baseline_listing_keys")
    if not isinstance(keys, list) or any(not isinstance(k, str) or not k for k in keys):
        raise CollectionError("baseline_keys_invalid")
    if config.get("baseline_reviewed") is not True:
        raise CollectionError("baseline_ownership_review_required")
    if config.get("legacy_policy", "reviewed_baseline") not in ("reviewed_baseline", "preserve_unknown"):
        raise CollectionError("legacy_policy_invalid")
    if config.get("legacy_policy") == "preserve_unknown" and keys:
        raise CollectionError("unknown_ownership_cannot_claim_baseline")
    ratio = float(config.get("max_drop_ratio", 0.25))
    if not math.isfinite(ratio) or not 0 <= ratio <= 0.5 or not 1 <= int(config.get("max_rows", 5000)) <= 5000:
        raise CollectionError("collection_limits_invalid")


def only(locator, stage: str):
    """Wait for the live UI before asserting a single observed element.

    Playwright locator.count() returns immediately; calling it just after an
    authenticated navigation mistakes an ordinary render delay for a changed UI.
    Stage is a code-owned, non-sensitive identifier, never page text/HTML.
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    try:
        locator.first.wait_for(state="visible", timeout=30000)
    except PlaywrightTimeoutError:
        raise CollectionError("ulucks_ui_" + stage + "_missing") from None
    if locator.count() != 1:
        raise CollectionError("ulucks_ui_" + stage + "_ambiguous")
    return locator


def _search_form(page):
    area = only(page.get_by_label(AREA_LABEL, exact=True), "area_checkbox")
    if area.get_attribute("type") != "checkbox":
        raise CollectionError("ulucks_area_control_changed")
    form = only(area.locator("xpath=ancestor::form[1]"), "search_form")
    return form, area


def _assert_scope(page):
    title = page.get_by_text(re.compile(r"物件検索\s*[（(]\s*" + re.escape(COMPANY_LABEL) + r"\s*[）)]"))
    only(title, "company_title").wait_for(state="visible")
    form, area = _search_form(page)
    checked = form.locator('input[type="checkbox"]:checked')
    if checked.count() != 1 or not area.is_checked():
        raise CollectionError("ulucks_area_filter_not_exclusive")
    return form


def _search(page) -> int:
    form, area = _search_form(page)
    # The provided screen defaults to seven wards. Clear them all, then choose
    # only Kokurakita. Reset other search constraints to their neutral controls.
    form.evaluate("form => form.reset()")
    for box in form.locator('input[type="checkbox"]').all():
        box.uncheck()
    for text in form.locator('input[type="text"], input[type="search"]').all():
        text.fill("")
    for select in form.locator("select").all():
        option = select.locator("option").first
        select.select_option(value=option.get_attribute("value") or "")
    area.check()
    _assert_scope(page)
    button = form.get_by_role("button", name=re.compile(r"^検\s*索$"))
    if button.count() == 0:
        button = form.get_by_role("link", name=re.compile(r"^検\s*索$"))
    # Observe a real document/XHR response caused by the search. No fabricated
    # query parameters, city codes, form action or internal API endpoint.
    with page.expect_response(lambda r: urlsplit(r.url).netloc == urlsplit(ORIGIN).netloc and r.request.resource_type in ("document", "xhr", "fetch"), timeout=45000) as pending:
        only(button, "search_action").click()
    response = pending.value
    if response.status != 200:
        raise CollectionError("ulucks_search_http_failed")
    response.finished()
    page.wait_for_load_state("domcontentloaded")
    _assert_scope(page)
    body = normal(page.locator("body").inner_text())
    matches = re.findall(r"検索結果\s*([\d,]+)\s*件中", body)
    if len(matches) != 1:
        raise CollectionError("ulucks_result_count_not_confirmed")
    return int(matches[0].replace(",", ""))


def _capture_print(page, root: Path) -> tuple[list[Path], dict]:
    context = page.context
    action = only(page.get_by_role("link", name=PRINT_LABEL), "print_action")
    href = action.get_attribute("href")
    observed_href = urljoin(page.url, href or "")
    if not href or urlsplit(observed_href).netloc != urlsplit(ORIGIN).netloc:
        raise CollectionError("ulucks_print_link_not_verified")
    captured = []
    descriptors = []
    errors = []

    def intercept(route):
        request = route.request
        if request.resource_type not in ("document", "xhr", "fetch"):
            route.continue_()
            return
        try:
            response = route.fetch(timeout=60000)
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if int(response.headers.get("content-length", "0")) > 100 * 1024 * 1024:
                raise CollectionError("ulucks_export_too_large")
            if content_type in ("application/pdf", "application/octet-stream", "application/zip", "application/x-zip-compressed") and response.ok:
                data = response.body()
                if not data or len(data) > 100 * 1024 * 1024:
                    raise CollectionError("ulucks_export_size_invalid")
                target = root / "export.bin"
                target.write_bytes(data)
                captured.extend(unpack_export(target, root))
                descriptors.append({"method": request.method, "path": urlsplit(request.url).path, "content_type": content_type, "bytes": len(data)})
            route.fulfill(response=response)
        except Exception:
            errors.append("ulucks_print_response_failed")
            route.abort()

    pattern = ORIGIN + "/**"
    # Forward exactly the browser's observed request, including POST data and
    # session cookies. This also captures inline PDFs, popup PDFs and XHR blobs.
    context.route(pattern, intercept)
    try:
        try:
            action.click(no_wait_after=True)
        except Exception:
            if not captured:
                raise CollectionError("ulucks_print_action_failed") from None
        deadline = time.monotonic() + 65
        while not captured and not errors and time.monotonic() < deadline:
            page.wait_for_timeout(100)
        if errors or not captured:
            raise CollectionError("ulucks_original_pdf_not_received")
    finally:
        context.unroute(pattern, intercept)
    return captured, {"print_action": "area_property", "responses": descriptors}


def _observe_company_row(page, row, root: Path) -> tuple[list, dict]:
    """Inspect the actual authenticated row; never export its text or raw HTML.

    The private record contains only structural counts and boolean matches.
    Link destinations are evaluated in memory, not guessed from table columns.
    """
    root.parent.mkdir(parents=True, exist_ok=True)
    links = row.locator("a[href]").all()
    cells = row.locator("td").all()
    candidates = []
    for link in links:
        href = link.get_attribute("href") or ""
        url = urlsplit(urljoin(page.url, href))
        if (url.scheme == "https" and url.netloc == urlsplit(ORIGIN).netloc
                and url.path.rstrip("/") == "/company/lists/" + COMPANY_ID
                and not url.query and not url.fragment):
            candidates.append(link)
    report = {
        "stage": "company_row_observed",
        "target_row_unique": True,
        "cell_count": min(len(cells), 100),
        "link_count": min(len(links), 100),
        "link_cell_indexes": [
            i for i, cell in enumerate(cells[:100]) if cell.locator("a[href]").count()
        ],
        "expected_company_link_count": min(len(candidates), 100),
    }
    (root.parent / "ulucks-ui.private.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8"
    )
    # This allowlisted structural summary may also be read from Cloud Logging.
    # It contains no member text, URL, raw HTML, cookie, session or credentials.
    print("ULUCKS_UI_SAFE=" + json.dumps(report, ensure_ascii=False), flush=True)
    return candidates, report


def collect_with_page(page, config: dict, credentials: dict, root: Path) -> Collected:
    validate_config(config)
    if not credentials.get("username") or not credentials.get("password"):
        raise CollectionError("ulucks_credentials_incomplete")
    response = page.goto(ORIGIN + "/", wait_until="domcontentloaded", timeout=45000)
    if response is None or response.status != 200 or urlsplit(page.url).netloc != urlsplit(ORIGIN).netloc:
        raise CollectionError("ulucks_login_page_unavailable")
    # The supplied login screen has one text input, one password input and a
    # ログイン action. Values are never embedded in selectors or persisted.
    only(page.locator('input:not([type]):visible, input[type="text"]:visible, input[type="email"]:visible'), "login_username").fill(credentials["username"])
    only(page.locator('input[type="password"]:visible'), "login_password").fill(credentials["password"])
    login = page.get_by_role("button", name=re.compile(r"^ログイン$"))
    if login.count() == 0:
        login = page.get_by_role("link", name=re.compile(r"^ログイン$"))
    only(login, "login_action").click()
    company_search = only(page.get_by_role("link", name="会社検索", exact=True), "company_search")
    company_search.wait_for(state="visible", timeout=30000)
    company_search.click()
    # Inspect the live row before deciding how to navigate. A column index
    # inferred from a screenshot is never used as an operational selector.
    company_row = only(page.get_by_role("row").filter(
        has_text=re.compile(re.escape(COMPANY_LABEL))), "company_row")
    candidates, observation = _observe_company_row(page, company_row, root)
    if len(candidates) > 1:
        raise CollectionError("ulucks_company_target_links_ambiguous")
    if len(candidates) == 1:
        candidates[0].click()
        navigation = "observed_company_link"
        try:
            page.wait_for_url(lambda url: (urlsplit(str(url)).netloc == urlsplit(ORIGIN).netloc
                and urlsplit(str(url)).path.rstrip("/") == "/company/lists/8"), timeout=30000)
        except Exception:
            raise CollectionError("ulucks_company_scope_navigation_failed") from None
    else:
        # A known, user-reviewed URL may be used ONLY inside the authenticated
        # session, and ONLY after checking the target company heading below.
        response = page.goto(config["search_url"], wait_until="domcontentloaded", timeout=45000)
        if response is None or response.status != 200 or urlsplit(page.url).path.rstrip("/") != "/company/lists/8":
            raise CollectionError("ulucks_company_scope_navigation_failed")
        navigation = "authenticated_direct_verified"
    only(page.get_by_text(re.compile(r"物件検索\\s*[（(]\\s*" + re.escape(COMPANY_LABEL) + r"\\s*[）)]")), "company_title").wait_for(state="visible")
    observation["verified_company_title"] = True
    observation["navigation"] = navigation
    (root.parent / "ulucks-ui.private.json").write_text(json.dumps(observation, ensure_ascii=False), encoding="utf-8")
    count = _search(page)
    if count > int(config.get("max_rows", 5000)):
        raise CollectionError("ulucks_result_count_exceeds_limit")
    if count == 0:
        # A second fresh successful search distinguishes authenticated empty
        # results from a timeout/login failure or incomplete PDF generation.
        if _search(page) != 0:
            raise CollectionError("ulucks_zero_result_not_stable")
        return Collected([], 0, True, {"search_counts": [0, 0], "scope_verified": True, "company_navigation": navigation})
    root.mkdir(parents=True, exist_ok=True)
    paths, evidence = _capture_print(page, root)
    return Collected(paths, count, False, {**evidence, "acquired_at": datetime.now(timezone.utc).isoformat(), "search_counts": [count], "scope_verified": True, "company_navigation": navigation})


def unpack_export(target: Path, root: Path) -> list[Path]:
    if zipfile.is_zipfile(target):
        paths = []
        with zipfile.ZipFile(target) as archive:
            members = [info for info in archive.infolist() if not info.is_dir()]
            if not members or len(members) > 100 or sum(info.file_size for info in members) > 100 * 1024 * 1024:
                raise CollectionError("ulucks_zip_limits_failed")
            for index, info in enumerate(members):
                if not info.filename.lower().endswith(".pdf") or info.flag_bits & 1:
                    raise CollectionError("ulucks_zip_contains_unexpected_file")
                path = root / f"ulucks-{index:03d}.pdf"
                path.write_bytes(archive.read(info))
                paths.append(path)
    else:
        path = root / "ulucks-000.pdf"
        target.replace(path)
        paths = [path]
    for path in paths:
        from pypdf import PdfReader
        if not path.read_bytes().startswith(b"%PDF-"):
            raise CollectionError("ulucks_download_is_not_pdf")
        try:
            reader = PdfReader(path)
            if reader.is_encrypted or not 0 < len(reader.pages) <= 500 or any(not (page.extract_text() or "").strip() for page in reader.pages):
                raise CollectionError("ulucks_pdf_invalid_or_no_extractable_text")
        except CollectionError:
            raise
        except Exception:
            raise CollectionError("ulucks_pdf_invalid") from None
    return paths


def collect(config: dict, credentials: dict, root: Path) -> Collected:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=os.environ.get("TATEMONO_CHROMIUM_EXECUTABLE"))
        page = None
        try:
            context = browser.new_context(accept_downloads=True, locale="ja-JP")
            context.set_default_timeout(30000)
            page = context.new_page()
            return collect_with_page(page, config, credentials, root)
        except CollectionError:
            raise
        except Exception:
            raise CollectionError("ulucks_browser_failed") from None
        finally:
            # The supplied member UI has a limited concurrent-session counter.
            # Release this job's own session through the observed logout action.
            if page is not None and not page.is_closed():
                try:
                    logout = page.get_by_role("link", name="ログアウト", exact=True).or_(page.get_by_role("button", name="ログアウト", exact=True))
                    if logout.count() == 1 and logout.is_visible():
                        logout.click(timeout=5000)
                except Exception:
                    pass
            browser.close()
