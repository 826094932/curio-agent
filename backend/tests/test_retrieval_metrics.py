from evaluation.retrieval import judge, summarize, hard_violations


def item(id='phone-1', brand='Apple'):
    return {'id': id, 'category': 'phone', 'brand': brand, 'specs': {'storage_gb': 256},
            'price': {'final_price': '9999.00'}}


def test_oracle_checks_chinese_brand_and_missing_price_independently():
    assert hard_violations(item(), {'excluded_brands': ['苹果']}) == ['excluded_brand']
    assert hard_violations({**item(), 'price': {}}, {'budget_max': 10000}) == ['budget_max']
    assert hard_violations(item(), {'hard_constraints': {'storage_gb_gte': 512}}) == ['storage_gb_gte']


def test_missing_models_do_not_inflate_exact_hit_rate():
    case = {'expected_ids': [], 'target_groups': [[]], 'state': {}}
    output = judge(case, {'items': []})
    assert output['case_pass'] is True and output['exact_hit'] is False
    assert output['all_targets_available'] is False and output['expected_empty'] is True
    assert output['recall_at_3'] is None
    related = judge({**case, 'family_ids': ['phone-1']}, {'family_items': [item()]})
    assert related['family_candidate_provided'] is True
    assert related['exact_hit'] is False and related['case_pass'] is True


def test_summary_separates_available_targets_from_absent_targets():
    existing = judge({'expected_ids': ['phone-1'], 'target_groups': [['phone-1']], 'state': {}}, {'items': [item()]})
    absent = judge({'expected_ids': [], 'target_groups': [[]], 'state': {}}, {'items': []})
    rows = [{'case_id': str(i), 'group': 'test', 'status': 'succeeded', 'search_ms': latency, **data}
            for i, (data, latency) in enumerate([(existing, 10), (absent, 20)])]
    result = summarize(rows)
    assert result['exact_requested_hit_rate'] == .5
    assert result['available_target_hit_rate'] == 1
    assert result['zero_result_rate'] == .5
    assert result['case_pass_rate'] == 1
    assert result['search_p50_ms'] == 15 and result['search_p95_ms'] == 20
    assert result['first_token_p50_ms'] is None
