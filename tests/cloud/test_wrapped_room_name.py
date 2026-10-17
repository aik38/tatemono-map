from tatemono_map.cli.pdf_batch_run import ulucks_building_name


def test_labelled_wrapped_room_requires_exact_independent_cell_agreement():
    assert ulucks_building_name('架空駅前Ⅱ5 01号室', '501') == '架空駅前II'
    assert ulucks_building_name('架空駅前Ⅱ5 01号室', '502') == '架空駅前Ⅱ5 01号室'
    assert ulucks_building_name('架空駅前Ⅱ5', '5') == '架空駅前Ⅱ5'
    assert ulucks_building_name('架空駅前 001号室', '1') == '架空駅前 001号室'
    assert ulucks_building_name('架空駅前 001号室', '001') == '架空駅前'
    assert ulucks_building_name('架空ビル第3 5 01号室', '501') == '架空ビル第3'
