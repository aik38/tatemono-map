"""Login-only Cloud Run proof. Never acquires PDFs or opens the canonical store."""
from __future__ import annotations

import hashlib
import json
import os
from urllib.parse import urlsplit

from google.cloud import secretmanager
from playwright.sync_api import sync_playwright
from tatemono_map.cloud.collector import CollectionError
from tatemono_map.cloud.realpro import login


def main():
    evidence = {'diagnostic': 'realpro_login_only', 'source_commit': os.environ.get('TATEMONO_SOURCE_COMMIT')}
    try:
        ref = os.environ['REALPRO_LOGIN_SECRET']
        response = secretmanager.SecretManagerServiceClient().access_secret_version(request={'name': ref})
        evidence.update(secret_reference=ref, secret_version=response.name.rsplit('/', 1)[-1])
        credentials = json.loads(response.payload.data)
        del response
        with sync_playwright() as p:
            options = {'headless': True}
            if os.environ.get('TATEMONO_CHROMIUM_EXECUTABLE'):
                options['executable_path'] = os.environ['TATEMONO_CHROMIUM_EXECUTABLE']
            browser = p.chromium.launch(**options)
            try:
                context = browser.new_context(locale='ja-JP', viewport={'width': 1536, 'height': 900})
                evidence['initial_cookie_count'] = len(context.cookies())
                page = context.new_page()
                page = login(page, credentials)
                current = urlsplit(page.url)
                reached = (
                    current.hostname == 'www.realnetpro.com'
                    and current.path == '/main.php'
                    and page.locator('#company_place').is_visible()
                    and not page.locator('input[type=password]:visible').count()
                )
                if not reached:
                    raise CollectionError('realpro_company_list_not_confirmed')
                evidence.update(result='success', company_list_reached=True,
                                final_host=current.hostname, final_path=current.path)
            finally:
                browser.close()
        print('REALPRO_LOGIN_SAFE=' + json.dumps(evidence, ensure_ascii=False), flush=True)
        return 0
    except CollectionError as exc:
        evidence.update(result='failed', failure_code=str(exc))
    except Exception as exc:
        evidence.update(result='failed', failure_code='realpro_login_operation_failed',
                        error_type=type(exc).__name__)
    print('REALPRO_LOGIN_SAFE=' + json.dumps(evidence, ensure_ascii=False), flush=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
