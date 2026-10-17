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
    target = {
        "login_url": ORIGIN + "/", "search_url": ORIGIN + "/company/lists/8",
        "company_id": COMPANY_ID, "company_label": COMPANY_LABEL,
        "area_id": "kokurakita", "area_label": AREA_LABEL,
        "address_contains": "小倉北区",
    }
    if config.get('area_id') == 'kitakyushu':
        target.update(area_id='kitakyushu', area_label='北九州', address_contains='kitakyushu')
    if any(config.get(k) != v for k, v in target.items()):
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


def _area_structure(area) -> dict:
    """Live DOM facts only: never return the input value, id, page text or HTML."""
    return area.evaluate("""el => {
        const labels = Array.from(el.labels || []);
        const visible = node => {
            const r = node.getBoundingClientRect();
            const style = getComputedStyle(node);
            return !!(r.width && r.height && style.visibility !== 'hidden' && style.display !== 'none');
        };
        return {
            input_connected: el.isConnected,
            input_is_checkbox: el.tagName === 'INPUT' && el.type === 'checkbox',
            input_visible: visible(el),
            input_disabled: !!el.disabled,
            input_checked: !!el.checked,
            associated_label_count: Math.min(labels.length, 10),
            associated_label_visible: labels.length === 1 && visible(labels[0]),
            label_wraps_input: labels.length === 1 && labels[0].contains(el),
            label_for_input: labels.length === 1 && !!el.id && labels[0].htmlFor === el.id
        };
    }""")


def _playwright_failure_reason(exc: Exception) -> str:
    """Classify known Playwright actionability failures without publishing their text."""
    message = str(exc).lower()
    for needle, code in (
        ("intercepts pointer events", "pointer_intercepted"),
        ("not visible", "not_visible"),
        ("detached", "element_detached"),
        ("not enabled", "disabled"),
        ("outside of the viewport", "outside_viewport"),
        ("timeout", "timeout"),
    ):
        if needle in message:
            return code
    return "other"


def _activate_observed_area(area, root: Path) -> None:
    """Use the observed checkbox, then its *actual* associated label if needed.

    A native Playwright check is preferred. The fallback is a real pointer click
    on the unique DOM-associated label, never a fabricated selector/force=True.
    Both paths must result in the same actual checked input.
    """
    before = _area_structure(area)
    if not before["input_connected"] or not before["input_is_checkbox"] or before["input_disabled"]:
        raise CollectionError("ulucks_area_dom_contract_invalid")
    record = {"stage": "area_activation", "before": before, "method": "native_check"}
    if area.is_checked():
        record["method"] = "already_checked"
    else:
        try:
            area.check(timeout=7500)
        except Exception as exc:
            record["first_error_class"] = type(exc).__name__ if type(exc).__name__ in (
                "TimeoutError", "Error", "TargetClosedError") else "other"
            record["first_error_reason"] = _playwright_failure_reason(exc)
            # Query again after the action: event handlers may have replaced the input.
            after_failure = _area_structure(area)
            record["after_native_failure"] = after_failure
            if not area.is_checked():
                if (after_failure["associated_label_count"] != 1
                        or not after_failure["associated_label_visible"]
                        or after_failure["input_disabled"]):
                    _append_ui_observation(root, "area_activation", record)
                    print("ULUCKS_UI_SAFE=" + json.dumps(record, ensure_ascii=False), flush=True)
                    raise CollectionError("ulucks_area_observed_label_unavailable") from None
                label_handle = area.evaluate_handle(
                    "el => el.labels && el.labels.length === 1 ? el.labels[0] : null")
                label = label_handle.as_element()
                if label is None:
                    raise CollectionError("ulucks_area_observed_label_unavailable") from None
                record["method"] = "observed_associated_label_click"
                try:
                    label.click(timeout=9000)
                except Exception as label_exc:
                    record["label_error_reason"] = _playwright_failure_reason(label_exc)
                    record["label_error_class"] = type(label_exc).__name__ if type(label_exc).__name__ in (
                        "TimeoutError", "Error", "TargetClosedError") else "other"
    record["after"] = _area_structure(area)
    _append_ui_observation(root, "area_activation", record)
    print("ULUCKS_UI_SAFE=" + json.dumps(record, ensure_ascii=False), flush=True)
    if not area.is_checked():
        raise CollectionError("ulucks_area_not_activated")


_SEARCH_ACTION_CSS = ('button, input[type="submit"], input[type="button"], '
                      'input[type="image"], a, [role="button"], [onclick]')


def _observed_search_action(page, root: Path, form=None):
    """Inspect real clickable DOM. Never infer a fixed selector from screenshots.

    Choose an observed and unique search-labelled action. Only if the live
    source form has exactly one submit action may it be used without a label.
    No raw page labels, URLs, attributes, HTML or session data leave the browser.
    """
    form_index = form.evaluate("el => Array.from(document.forms).indexOf(el)") if form is not None else -1
    result = page.evaluate("""args => {
        const [css, formIndex] = args;
        const owningForm = document.forms[formIndex] || null;
        const controls = Array.from(document.querySelectorAll(css));
        const normal = s => String(s || '').normalize('NFKC').replace(/\\s+/g, '');
        const visible = el => {
            const r = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return !!(r.width && r.height && style.display !== 'none' && style.visibility !== 'hidden');
        };
        const common = new Set(['検索する', '検索実行', '検索開始', '物件検索', '物件を検索',
            'この条件で検索', 'この条件で検索する', '検索結果を表示', '再検索']);
        const excluded = /会社検索|検索条件|検索履歴|詳細検索|検索ヘルプ|クリア|リセット|間取|印刷/;
        const matches = [];
        controls.forEach((el, index) => {
            if (!visible(el) || el.disabled) return;
            const image = el.querySelector('img');
            const texts = [el.innerText, el.textContent, el.value, el.alt, el.title,
                el.getAttribute('aria-label'), image && image.alt, image && image.title]
                .map(normal).filter(Boolean);
            const exact = texts.some(x => x === '検索');
            const commonSearch = texts.some(x => common.has(x));
            const searchText = texts.some(x => x.includes('検索') && !excluded.test(x));
            const hints = [el.id, el.className, el.getAttribute('name'),
                el.getAttribute('data-action'), el.getAttribute('aria-label'), el.getAttribute('onclick'),
                image && image.getAttribute('src')].map(x => String(x || ''));
            const attributeHint = hints.some(x => /search|kensaku|検索/i.test(x));
            const inForm = !!owningForm && (el.closest('form') === owningForm || el.form === owningForm);
            const submit = inForm && ((el.tagName === 'INPUT' &&
                ['submit', 'image'].includes(el.type)) || el.tagName === 'BUTTON' &&
                (!el.type || el.type === 'submit'));
            if (exact || commonSearch || searchText || attributeHint || submit) {
                matches.push({index, tag: el.tagName.toLowerCase(),
                    type: ['submit', 'button', 'image'].includes(el.type) ? el.type : 'other',
                    exact, commonSearch, searchText, attributeHint, submit, inForm});
            }
        });
        // The live ID-8 page has navigation links named "物件検索" outside
        // the search form. Prefer observed actions belonging to the exact form
        // that contains the verified Kokurakita checkbox. Never choose its
        // navigation link over a unique search-labelled form submit.
        const scoped = matches.filter(x => x.inForm);
        const groups = [
            ['form_exact_label', scoped.filter(x => x.exact)],
            ['form_common_search_label', scoped.filter(x => x.commonSearch)],
            ['form_search_label', scoped.filter(x => x.searchText)],
            ['form_search_attribute', scoped.filter(x => x.attributeHint && x.tag !== 'div')],
            ['form_unique_submit', scoped.filter(x => x.submit)]
        ];
        if (scoped.length === 0) {
            const external = matches.filter(x => !x.inForm);
            groups.push(
                ['external_exact_label', external.filter(x => x.exact)],
                ['external_common_search_label', external.filter(x => x.commonSearch)],
                ['external_search_label', external.filter(x => x.searchText)],
                ['external_search_attribute', external.filter(x => x.attributeHint && x.tag !== 'div')]
            );
        }
        let chosen = null, reason = 'none';
        for (const [kind, entries] of groups) {
            if (entries.length > 1) {reason = 'ambiguous_' + kind; break;}
            if (entries.length === 1) {chosen = entries[0]; reason = kind; break;}
        }
        return {candidate_count: Math.min(controls.length, 500),
            search_related_count: Math.min(matches.length, 100),
            chosen_index: chosen ? chosen.index : -1, selection_reason: reason,
            candidates: matches.slice(0, 12).map(x => ({
                tag: x.tag, type: x.type, exact: x.exact, commonSearch: x.commonSearch,
                searchText: x.searchText, attributeHint: x.attributeHint,
                submit: x.submit, inForm: x.inForm
            }))};
    }""", [_SEARCH_ACTION_CSS, form_index])
    record = {
        "stage": "search_action_observed",
        "candidate_count": result["candidate_count"],
        "search_related_count": result["search_related_count"],
        "selection_reason": result["selection_reason"],
        "candidate_structures": result["candidates"],
    }
    _append_ui_observation(root, "search_action_observed", record)
    print("ULUCKS_UI_SAFE=" + json.dumps(record, ensure_ascii=False), flush=True)
    if result["chosen_index"] < 0:
        raise CollectionError("ulucks_search_action_not_unique")
    return page.locator(_SEARCH_ACTION_CSS).nth(result["chosen_index"])


def _confirmed_result_count(body: str) -> int:
    # Live Cloud Run observation 20261017T094004Z: the same result summary
    # appears above AND below the listing cards. Require their agreement,
    # not exactly one occurrence, and reject absent/conflicting summaries.
    counts = {int(value.replace(",", "")) for value in
              re.findall(r"検索結果\s*([\d,]+)\s*件中", normal(body))}
    if len(counts) != 1:
        raise CollectionError("ulucks_result_count_not_confirmed")
    return counts.pop()


def _search(page, root: Path) -> int:
    phase = "form_lookup"
    try:
        form, area = _search_form(page)
        # This is an observation of the real authenticated form, not guessed
        # selectors or an exported member page. No input values are captured.
        shape = {
            "stage": "search_controls",
            "form_count": min(page.locator("form").count(), 100),
            "checkbox_count": min(form.locator('input[type="checkbox"]').count(), 100),
            "checked_count": min(form.locator('input[type="checkbox"]:checked').count(), 100),
            "text_input_count": min(form.locator('input[type="text"], input[type="search"]').count(), 100),
            "select_count": min(form.locator("select").count(), 100),
            "search_button_count": min(form.get_by_role("button", name=re.compile(r"^検\s*索$")).count(), 100),
            "search_link_count": min(form.get_by_role("link", name=re.compile(r"^検\s*索$")).count(), 100),
            "area_is_checked": area.is_checked(),
            "page_search_button_count": min(page.get_by_role("button", name=re.compile(r"^検\s*索$")).count(), 100),
            "page_search_link_count": min(page.get_by_role("link", name=re.compile(r"^検\s*索$")).count(), 100),
        }
        _append_ui_observation(root, "search_controls", shape)
        print("ULUCKS_UI_SAFE=" + json.dumps(shape, ensure_ascii=False), flush=True)
        # The observed member form has at least 100 checkboxes and eight
        # selects. Clearing every checkbox/resetting every select changes
        # unrelated criteria and can detach the area checkbox. Only known
        # municipality-area controls are changed after live label lookup.
        phase = "area_controls"
        ward_labels = ("門司区", "小倉北区", "小倉南区", "若松区",
                       "八幡東区", "八幡西区", "戸畑区")
        area_controls = []
        for label in ward_labels:
            matches = form.get_by_label(label, exact=True)
            if matches.count() > 1:
                raise CollectionError("ulucks_area_label_ambiguous")
            if matches.count() == 1:
                if matches.get_attribute("type") != "checkbox":
                    raise CollectionError("ulucks_area_control_changed")
                area_controls.append((label, matches))
        if not any(label == AREA_LABEL for label, _ in area_controls):
            raise CollectionError("ulucks_area_target_not_in_form")
        _append_ui_observation(root, "area_controls", {
            "recognized_ward_controls": len(area_controls),
            "initially_checked_wards": sum(c.is_checked() for _, c in area_controls),
        })
        phase = "area_other_wards_clear"
        for label, control in area_controls:
            if label != AREA_LABEL and control.is_checked():
                control.uncheck()
        phase = "text_filters_verify"
        # Fresh direct navigation should have neutral text filters. Do not
        # silently edit other search constraints if this assumption changes.
        for field in form.locator('input[type="text"], input[type="search"]').all():
            if field.input_value().strip():
                raise CollectionError("ulucks_nonempty_search_text_requires_review")
        phase = "area_check"
        _activate_observed_area(area, root)
        phase = "scope_verify_before"
        _assert_scope(page)
        phase = "search_action"
        button = _observed_search_action(page, root, form)
        submission = form.evaluate("el => ({url: el.action, method: el.method.toUpperCase()})")
        # Use only the actual browser request and response.
        phase = "search_response"
        with page.expect_response(lambda r: r.url == submission["url"]
                                  and r.request.method == submission["method"]
                                  and r.request.resource_type == "document"
                                  and r.frame == page.main_frame, timeout=45000) as pending:
            button.click()
        response = pending.value
        if response.status != 200:
            raise CollectionError("ulucks_search_http_failed")
        response.finished()
        phase = "search_dom_ready"
        page.wait_for_load_state("domcontentloaded")
        # Search scope was verified on the live submission form. The results
        # may replace or omit its checkboxes. Requiring the old form after
        # submission caused a false collection failure in live run 38944515298.
        # Confirm actual results instead; PDF parsing enforces area per row.
        phase = "result_count"
        try:
            page.wait_for_function("""() => /検索結果\\s*[\\d,]+\\s*件中/.test(
                (document.body && document.body.innerText || '').normalize('NFKC')
            )""", timeout=45000)
        except Exception:
            _append_ui_observation(root, "post_search_state", {
                "stage": "post_search_state",
                "result_marker_present": False,
                "form_present": page.locator("form").count() > 0,
                "area_checkbox_present": page.get_by_label(AREA_LABEL, exact=True).count() > 0,
                "response_resource_type": response.request.resource_type,
                "response_ok": response.ok,
            })
            raise CollectionError("ulucks_result_count_not_confirmed") from None
        body = normal(page.locator("body").inner_text())
        matches = re.findall(r"検索結果\s*([\d,]+)\s*件中", body)
        _append_ui_observation(root, "post_search_state", {
            "stage": "post_search_state",
            "result_marker_present": bool(matches),
            "form_present": page.locator("form").count() > 0,
            "area_checkbox_present": page.get_by_label(AREA_LABEL, exact=True).count() > 0,
            "response_resource_type": response.request.resource_type,
            "response_ok": response.ok,
        })
        count = _confirmed_result_count(body)
        _append_ui_observation(root, "search_completed", {"result_count": count,
            "matching_summary_count": len(matches), "response_method": response.request.method})
        return count
    except CollectionError:
        raise
    except Exception:
        # The exception message may include form HTML, account data or request
        # URLs. Only the code-owned stage is retained; never print the message.
        event = {"stage": "search_exception", "operation": phase}
        _append_ui_observation(root, "search_exception", event)
        print("ULUCKS_UI_SAFE=" + json.dumps(event, ensure_ascii=False), flush=True)
        raise CollectionError("ulucks_search_browser_failed") from None


def _append_ui_observation(root: Path, key: str, value: dict) -> None:
    path = root.parent / "ulucks-ui.private.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    current[key] = value
    path.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")

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
    # Live 2026-10-18 UI uses a clickable TD[data-href], not an anchor.
    links = row.locator("a[href], td[data-href]").all()
    cells = row.locator("td").all()
    candidates = []
    for link in links:
        href = link.get_attribute("href") or link.get_attribute('data-href') or ""
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
    only(page.get_by_text(re.compile(r"物件検索\s*[（(]\s*" + re.escape(COMPANY_LABEL) + r"\s*[）)]")), "company_title").wait_for(state="visible")
    observation["verified_company_title"] = True
    observation["navigation"] = navigation
    print("ULUCKS_UI_SAFE=" + json.dumps({"stage": "company_title_verified", "navigation": navigation, "verified_company_title": True}, ensure_ascii=False), flush=True)
    (root.parent / "ulucks-ui.private.json").write_text(json.dumps(observation, ensure_ascii=False), encoding="utf-8")
    count = _search(page, root)
    if count > int(config.get("max_rows", 5000)):
        raise CollectionError("ulucks_result_count_exceeds_limit")
    if count == 0:
        # A second fresh successful search distinguishes authenticated empty
        # results from a timeout/login failure or incomplete PDF generation.
        if _search(page, root) != 0:
            raise CollectionError("ulucks_zero_result_not_stable")
        return Collected([], 0, True, {"search_counts": [0, 0], "scope_verified": True, "company_navigation": navigation})
    root.mkdir(parents=True, exist_ok=True)
    _append_ui_observation(root, "print_started", {"stage": "print_started"})
    print('ULUCKS_UI_SAFE={"stage":"print_started"}', flush=True)
    try:
        paths, evidence = _capture_print(page, root)
    except CollectionError:
        raise
    except Exception:
        _append_ui_observation(root, "print_exception", {"stage": "print_exception"})
        print('ULUCKS_UI_SAFE={"stage":"print_exception"}', flush=True)
        raise CollectionError("ulucks_print_browser_failed") from None
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
            if config.get('area_id') == 'kitakyushu':
                from tatemono_map.cloud.wide import collect_with_page as wide_collect
                return wide_collect(page, config, credentials, root)
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
