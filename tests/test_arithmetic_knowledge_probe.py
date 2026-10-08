from triade.learning.knowledge_probe import _arithmetic_probe


def test_equation_probe_tests_application_and_preserves_negative_control():
    probe = _arithmetic_probe('unit', 'ledger quantity: total=(units*9+2)%41. Observed constraint.')
    assert probe is not None
    assert probe.production_eligible is False  # interpretation alone is not fact verification
    assert '(units*9+2)%41' not in probe.question
    assert probe.expected not in probe.question
    assert probe.evaluator('{"expression":"(units*9+2)%41"}')
    assert not probe.evaluator('{"expression":"units*9+2%41"}')
    assert not probe.evaluator('{"expression":null}')
    assert not probe.evaluator('{"expression":"__import__(\"os\")"}')


def test_unsupported_equations_are_not_certified():
    for content in ('x=__import__("os")', 'x=a+b.', 'x=a**99999.', 'x=a//2.', 'x=1.5.', 'x=a*1.5.', 'x=a[0].', 'status=ready.', 'x=x*2.'):
        assert _arithmetic_probe('unit', content) is None


def test_transfer_inputs_are_distinct_and_keep_rule_out_of_request():
    content = 'records: total=(units*9+2)%41. Observed constraint.'
    probes = [_arithmetic_probe('unit', content, input_value=x) for x in (3, 7, 34, 41)]
    assert len({p.question for p in probes}) == 4
    for probe in probes:
        assert '(units*9+2)%41' not in probe.question
        assert probe.evaluator('{"expression":"(units*9+2)%41"}')
    # Different formulas can coincide at one input; held-out diversity must
    # expose the regression rather than asserting impossible uniqueness.
    assert not all(p.evaluator('{"expression":"units*9+2%41"}') for p in probes)


def test_schema_proof_requires_actual_colocated_constraint(tmp_path):
    import json
    import sqlite3
    from triade.learning.knowledge_probe import _schema_provenance
    database=tmp_path/'source.db'
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE records(units INTEGER,total INTEGER CHECK(total=(units*9+2)%41))')
        ddl=conn.execute("SELECT sql FROM sqlite_master WHERE name='records'").fetchone()[0]
    source=tmp_path/'observation.json'
    source.write_text(json.dumps({'database_ref':str(database),'table_name':'records','schema_observation':ddl}))
    content='quantity: total=(units*9+2)%41. Observed constraint.'
    assert _schema_provenance(tmp_path/'learning.db',str(source),content)
    assert not _schema_provenance(tmp_path/'learning.db',str(source),content.replace('*9','*8'))
    assert not _schema_provenance(tmp_path/'other'/'learning.db',str(source),content)
    with sqlite3.connect(database) as conn:
        conn.execute('ALTER TABLE records ADD COLUMN extra INTEGER')
    assert not _schema_provenance(tmp_path/'learning.db',str(source),content)
