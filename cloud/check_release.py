#!/usr/bin/env python3
"""Hourly polling bridges successful Scheduler collection to existing Pages CI."""
import json
import os
from urllib.request import Request, urlopen


def main():
    enabled = os.environ.get("CLOUD_ENABLED") == "true"
    event = os.environ["EVENT_NAME"]
    build = event != "schedule"  # normal code pushes retain existing Pages behavior
    if enabled:
        from tatemono_map.cloud.storage import GCSStore, validate_head
        head, _ = GCSStore(os.environ["GCP_BUCKET"]).read_head()
        validate_head(head)
        if head["report"].get("bootstrap") or not head["report"].get("proof"):
            raise SystemExit("no successful full collection release yet; Pages unchanged")
        if event == "schedule":
            build = True
            try:
                request = Request("https://www.tatemono-map.com/cloud_release.json", headers={"Cache-Control": "no-cache"})
                with urlopen(request, timeout=30) as response:
                    live = json.load(response)
                build = live.get("run_id") != head["run_id"] or live.get("public_sha256") != head["public"]["sha256"]
            except Exception:
                pass  # missing production marker requires the first cloud publish
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"build={str(build).lower()}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("cloud release check failed; Pages unchanged") from None
