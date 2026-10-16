from __future__ import annotations
import json
import sys
import pytest
from test_setup import module, ROOT
from tatemono_map.cloud.collector import validate_config, CollectionError
from tatemono_map.cloud.public_db import sha256


def test_readonly_preflight_checks_real_db_and_never_calls_remote(master, tmp_path, monkeypatch):
    mod = module('initial_release')
    actual = mod.audit(master)
    monkeypatch.setattr(mod, 'EXPECTED', sha256(master))
    monkeypatch.setattr(mod, 'FINGERPRINT', actual['canonical_id_fingerprint'])
    review = tmp_path / 'review.json'
    review.write_text(json.dumps({'selected': actual, 'ulucks_total_rows': 4006, 'kokurakita_rows': [{}] * 2195, 'ownership_decided': False}))
    (tmp_path / 'cloud').mkdir()
    (tmp_path / 'cloud/collection.example.json').write_text((ROOT / 'cloud/collection.example.json').read_text())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, 'command', lambda *_a, **_k: pytest.fail('remote operation in read-only preflight'))
    monkeypatch.setattr(sys, 'argv', ['initial_release', '--master', str(master), '--review', str(review)])
    mod.main()
    contract = json.loads((tmp_path / 'work/initial-release/collection.private.json').read_text())
    assert contract['legacy_policy'] == 'preserve_unknown'
    assert contract['baseline_listing_keys'] == []
    assert not (tmp_path / 'work/initial-release/progress.private.json').exists()
    review.write_text(json.dumps({'selected': {**actual, 'counts': {}}, 'ownership_decided': False}))
    with pytest.raises(RuntimeError, match='review_does_not_match'):
        mod.check_inputs(master, review)


def test_preserve_unknown_cannot_claim_legacy_keys(config):
    config.update(legacy_policy='preserve_unknown', baseline_listing_keys=['unproven-key'])
    with pytest.raises(CollectionError, match='cannot_claim'):
        validate_config(config)


def test_dispatch_resume_is_correlated_and_duplicates_refused():
    mod = module('initial_release')
    run = {'id': 1, 'head_sha': 'a'*40, 'display_title': 'Ulucks initial nonce'}
    assert mod.deployment_run([run], 'nonce', 'a'*40) == run
    assert mod.deployment_run([run], 'other', 'a'*40) is None
    assert mod.deployment_run([run], 'nonce', 'b'*40) is None
    with pytest.raises(RuntimeError, match='multiple_deployment'):
        mod.deployment_run([run, {**run, 'id': 2}], 'nonce', 'a'*40)


def test_resume_unknown_dispatch_never_dispatches_again(tmp_path, monkeypatch):
    mod = module('initial_release')
    monkeypatch.chdir(tmp_path)
    (tmp_path/'cloud').mkdir()
    (tmp_path/'cloud/collection.example.json').write_text((ROOT/'cloud/collection.example.json').read_text())
    settings = tmp_path/'setup.json'
    settings.write_text((ROOT/'cloud/setup.example.json').read_text())
    progress = tmp_path/'work/initial-release/progress.private.json'
    progress.parent.mkdir(parents=True)
    progress.write_text(json.dumps({'commit':'a'*40,'nonce':'nonce','setup_complete':True,'dispatch_intent':True}))
    calls=[]
    def command(args, **kwargs):
        calls.append(args)
        if 'rev-parse' in args or '.object.sha' in args: return 'a'*40
        if 'status' in args: return ''
        if '/runs?' in ' '.join(args): return {'workflow_runs':[]}
        pytest.fail('unexpected mutation: ' + str(args[:3]))
    monkeypatch.setattr(mod, 'command', command)
    monkeypatch.setattr(mod, 'check_inputs', lambda *_: {})
    monkeypatch.setattr(sys, 'argv', ['initial_release','--activate','--reviewed-commit','a'*40,'--config',str(settings)])
    with pytest.raises(RuntimeError, match='dispatch_outcome_pending'):
        mod.main()
    assert not any(args[1:3] == ['workflow','run'] for args in calls)


@pytest.mark.parametrize('room', ['0101', '101号', '未定', '1-2', ''])
def test_ambiguous_unit_labels_are_not_assumed_distinct(room):
    from tatemono_map.cloud.pipeline import unit_room
    with pytest.raises(CollectionError, match='identity_ambiguous'):
        unit_room(room)


def test_room_normalization_is_exact_and_does_not_use_rent_or_area():
    from tatemono_map.cloud.pipeline import unit_room
    assert unit_room('１０１号室') == unit_room('101')
    assert unit_room('ａ１０１') == unit_room('A101')
    assert unit_room('101') != unit_room('102')
