#!/usr/bin/env python3
"""Read-only, allowlisted diagnosis after a failed live collection.

Runs in the already authenticated main deployment job. No raw logs, HTML,
credentials, URLs or member data ever enter public GitHub Actions logs.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone

from google.cloud import storage


def diagnostic():
    run = os.environ["GITHUB_RUN_ID"]
    bucket = storage.Client(project=os.environ["GCP_PROJECT_ID"]).bucket(os.environ["GCP_BUCKET"])
    receipt = bucket.blob(f"deployment-backups/execution-intents/{run}.json")
    try:
        receipt.reload(timeout=30)
        before = json.loads(receipt.download_as_bytes(if_generation_match=int(receipt.generation), timeout=30))
    except Exception as exc:
        return {"phase": "intent_unavailable", "error_class": type(exc).__name__}
    prior = set(before["previous_executions"])
    project, region, job = (os.environ[k] for k in ("GCP_PROJECT_ID", "GCP_REGION", "GCP_JOB"))
    def read(*args):
        result = subprocess.run(["gcloud", *args, "--project", project, "--quiet"], capture_output=True,
                                text=True, timeout=85)
        if result.returncode:
            text = result.stderr
            errors = [name for name,pattern in (("PERMISSION_DENIED",r"PERMISSION_DENIED|403"),
                ("NOT_FOUND",r"NOT_FOUND|404"),("INVALID_ARGUMENT",r"INVALID_ARGUMENT|400"),
                ("DEADLINE_EXCEEDED",r"DEADLINE_EXCEEDED|timeout")) if re.search(pattern,text,re.I)]
            return None, {"status": "failed", "error_classes": errors}
        try: return json.loads(result.stdout), {"status":"ok"}
        except ValueError: return None, {"status":"non_json"}
    executions,status = read("run","jobs","executions","list","--job",job,"--region",region,"--format=json")
    if not isinstance(executions,list):return {"phase":"execution_lookup","result":status}
    new = [x for x in executions if x.get("metadata",{}).get("name") not in prior]
    if len(new)!=1:return {"phase":"execution_uncertain","new_execution_count":len(new)}
    row=new[0]
    name=row["metadata"]["name"]
    created=row.get("metadata",{}).get("creationTimestamp")
    state=row.get("status") or {}
    out={"phase":"execution_observed","complete":bool(state.get("completionTime")),
         "failed_count":state.get("failedCount"),"succeeded_count":state.get("succeededCount")}
    if not created: return out
    start=(datetime.fromisoformat(created.replace("Z","+00:00"))-timedelta(seconds=10)).isoformat()
    query=('resource.type="cloud_run_job" AND resource.labels.job_name="'+job+
           '" AND timestamp>="'+start+'"')
    entries,log_status=read("logging","read",query,"--limit=200","--format=json")
    if not isinstance(entries,list):
        out["log_query"]=log_status
        return out
    allowed=set((
        "ulucks_browser_failed ulucks_credentials_incomplete ulucks_login_page_unavailable "
        "ulucks_area_control_changed ulucks_area_filter_not_exclusive ulucks_search_http_failed "
        "ulucks_result_count_not_confirmed ulucks_print_link_not_verified ulucks_export_too_large "
        "ulucks_export_size_invalid ulucks_print_action_failed ulucks_original_pdf_not_received "
        "ulucks_zero_result_not_stable ulucks_company_scope_navigation_failed ulucks_pdf_invalid ulucks_download_is_not_pdf "
        "ulucks_pdf_invalid_or_no_extractable_text cloud_operation_failed legacy_unit_identity_ambiguous "
        "ulucks_parser_qc_failed pdf_rows_do_not_match_result_count ingest_unmatched_or_suspect_rows "
        "ulucks_company_target_links_ambiguous ui_observation_private_upload_failed ulucks_search_browser_failed ulucks_print_browser_failed"
    ).split())
    stage_names=(
        "area_checkbox search_form company_title search_action print_action login_username "
        "login_password login_action company_search company_link company_row company_count_link"
    ).split()
    allowed.update(f"ulucks_ui_{stage}_{state}" for stage in stage_names for state in ("missing","ambiguous"))
    severity={}
    codes=set()
    ui_structure=[]
    for item in entries:
        resource=(item.get("resource") or {}).get("labels") or {}
        labels=item.get("labels") or {}
        observed=resource.get("execution_name") or labels.get("run.googleapis.com/execution_name")
        if observed and observed!=name: continue
        sev=str(item.get("severity","DEFAULT"))
        severity[sev]=severity.get(sev,0)+1
        payload=item.get("jsonPayload")
        text=" ".join([str(payload.get("code","")),str(payload.get("message",""))] if isinstance(payload,dict)
                      else [str(item.get("textPayload",""))])
        codes.update(code for code in re.findall(r"\b[a-z][a-z0-9_]{4,80}\b",text) if code in allowed)
        # Accept only an allowlisted structural projection of the collector's
        # own marker. Never forward arbitrary GCP log fields to public Actions.
        if text.startswith("ULUCKS_UI_SAFE="):
            try:
                record=json.loads(text[len("ULUCKS_UI_SAFE="):])
                if record.get("stage") == "company_row_observed":
                    keys=("stage","target_row_unique","cell_count","link_count",
                          "link_cell_indexes","expected_company_link_count")
                    values={k:record[k] for k in keys if k in record}
                    if (type(values.get("target_row_unique")) is bool
                        and all(type(values.get(k)) is int and 0<=values[k]<=100
                            for k in ("cell_count","link_count","expected_company_link_count"))
                        and isinstance(values.get("link_cell_indexes"),list)
                        and all(type(i) is int and 0<=i<100 for i in values["link_cell_indexes"][:100])):
                        values["link_cell_indexes"]=values["link_cell_indexes"][:100]
                        ui_structure.append(values)
                elif record.get("stage") == "search_controls":
                    names=("form_count","checkbox_count","checked_count","text_input_count",
                           "select_count","search_button_count","search_link_count")
                    if (all(type(record.get(k)) is int and 0<=record[k]<=100 for k in names)
                        and type(record.get("area_is_checked")) is bool):
                        ui_structure.append({"stage":"search_controls",
                            **{k:record[k] for k in names}, "area_is_checked":record["area_is_checked"]})
                elif record.get("stage") == "search_exception":
                    operation=record.get("operation")
                    if operation in ("form_lookup","form_reset","checkbox_clear","text_clear",
                                     "select_reset","area_check","scope_verify_before","search_action",
                                     "search_response","search_dom_ready","scope_verify_after","result_count"):
                        ui_structure.append({"stage":"search_exception","operation":operation})
                elif record.get("stage") in ("print_started","print_exception"):
                    ui_structure.append({"stage":record["stage"]})
                elif record.get("stage") == "company_title_verified":
                    if record.get("navigation") in ("observed_company_link","authenticated_direct_verified") and record.get("verified_company_title") is True:
                        ui_structure.append({"stage":"company_title_verified","navigation":record["navigation"],
                                             "verified_company_title":True})
            except (ValueError, TypeError, KeyError):
                pass
    out["log_severity_counts"]=severity
    out["safe_failure_codes"]=sorted(codes)
    out["safe_ui_observation"]=ui_structure[-6:]
    return out


if __name__ == "__main__":
    try:
        result=diagnostic()
    except Exception as exc:
        result={"phase":"safe_diagnostic_failed","error_class":type(exc).__name__}
    print("SAFE_COLLECTION_FAILURE="+json.dumps(result,ensure_ascii=False,sort_keys=True))
