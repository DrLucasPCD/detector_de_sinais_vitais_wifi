.PHONY: bootstrap demo serve simulator test clean

bootstrap:
	./scripts/bootstrap.sh

demo:
	./scripts/run-demo.sh

serve:
	.venv/bin/python -m rf_sense serve

simulator:
	.venv/bin/python -m rf_sense simulate

test:
	.venv/bin/python -m pytest

clean:
	rm -rf build dist .pytest_cache .coverage htmlcov

