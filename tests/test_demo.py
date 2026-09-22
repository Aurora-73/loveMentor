from lovementor.demo import REPORT, main


def test_demo_is_synthetic_and_cautious(capsys):
    assert "synthetic demo" in REPORT
    assert "no personal data" in REPORT
    assert main() == 0
    assert "not a conclusion about intent" in capsys.readouterr().out
