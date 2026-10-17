from tatemono_map.cloud.run import all_company_proof_ready


def test_weekly_full_collection_requires_complete_proof_for_its_revision():
    head={'qc':'passed','source_commit':'a'*40,'report':{'collection_mode':'all_companies','company_count':69,'successful_companies':69}}
    assert all_company_proof_ready(head,'a'*40)
    assert not all_company_proof_ready(head,'b'*40)
    assert not all_company_proof_ready({**head,'report':{**head['report'],'successful_companies':68}},'a'*40)
    assert not all_company_proof_ready({**head,'report':{**head['report'],'collection_mode':'company8'}},'a'*40)
