"""Verify the installed distribution in isolated processes, without source imports."""

import argparse
import json
from pathlib import Path
import subprocess
import sys


PROBE = r'''
import importlib.metadata, json, os, sys
from pathlib import Path

output = Path(sys.argv[1])
for name in list(os.environ):
    if name.startswith(('THESIS_', 'DOCX_')):
        del os.environ[name]
os.environ.update({
    'THESIS_DATA_DIR': str(output / 'data'),
    'THESIS_TASK_STORE_MEMORY': 'false', 'THESIS_JOB_WORKER_ENABLED': 'false',
    'THESIS_DEEPSEEK_ENABLED': 'false', 'THESIS_DEEPSEEK_FALLBACK_TO_MOCK': 'true',
    'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
})
import application
installed = Path(importlib.metadata.distribution('deep-thesis').locate_file('application')).resolve()
assert Path(application.__file__).resolve().parent == installed, 'Source checkout masked installed package'
assert Path(sys.prefix).resolve() in installed.parents, 'Distribution is not in the selected environment'
from common.prompt_repo import load_template
for prompt_name in ('ring1_topic', 'ring2_review', 'ring3_agent', 'ring3_queries', 'ring4_review',
                    'ring5_outline', 'ring6_chapter', 'ring6_plan', 'ring7_polish', 'section_draft'):
    assert load_template(prompt_name)['prompt'], 'Packaged prompt is missing or empty'
from fastapi.testclient import TestClient
from application.main import app

with TestClient(app) as client:
    orchestration = app.state.orchestration
    if sys.argv[2] == 'create':
        created = client.post('/api/v1/console/tasks', json={
            'title': 'Installed package acceptance', 'degree': 'MASTER',
            'subject_field': 'CS', 'session_id': 'installed-check',
        }).json()
        assert created['code'] == 0, created
        task_id = created['data']['task_id']
        assert orchestration.run_ring1(task_id).code == 0
        orchestration._drafts.save(task_id=task_id, tenant_id='default', author_id='author',
            object_type='PROJECT_MEMORY_FORM', draft_key='project-memory:main',
            content={'notes': 'Installed draft'}, revision=2)
        generated = orchestration._docx.generate('builtin', {
            'title': 'Installed template', 'main_body': 'Package template and renderer verification',
        }, session_id='installed-check')
        document = orchestration._knowledge_store.save_document('installed-check', 'source.txt', b'Local source')
        ids = {'task_id': task_id, 'file_id': generated['filename'], 'kb_id': document['file_id']}
        (output / 'identifiers.json').write_text(json.dumps(ids), encoding='utf-8')
    else:
        ids = json.loads((output / 'identifiers.json').read_text(encoding='utf-8'))
        assert orchestration._store.get(ids['task_id']).ring1
        assert orchestration.progress(ids['task_id']).data['phase_state'] == 'WAITING_APPROVAL'
        draft = orchestration._drafts.get(ids['task_id'], 'author', 'project-memory:main')
        assert draft.revision == 2 and draft.content_json == {'notes': 'Installed draft'}
        document = orchestration._knowledge_store.get_document('installed-check', ids['kb_id'])
        assert Path(document['file_path']).read_bytes() == b'Local source'
        downloaded = client.get('/api/v1/docx/files/' + ids['file_id'], params={'session_id': 'installed-check'})
        assert downloaded.status_code == 200 and downloaded.content.startswith(b'PK')
    assert orchestration.reconcile_startup().data['status'] == 'CONSISTENT'
    print(json.dumps({'phase': sys.argv[2], 'status': 'PASS',
                      'installed_path': str(installed), 'version': importlib.metadata.version('deep-thesis')}))
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description="Deep Thesis installed-package acceptance; no real model calls")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output_dir)
    if not output.is_absolute() or output.exists():
        parser.error("--output-dir must be absolute and must not exist")
    output.mkdir(parents=True)
    checked = subprocess.run([sys.executable, "-I", "-m", "pip", "check"], cwd=output,
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    (output / "dependency-check.log").write_text(checked.stdout + checked.stderr, encoding="utf-8")
    results = []
    if checked.returncode == 0:
        for phase in ("create", "restart"):
            result = subprocess.run([sys.executable, "-I", "-c", PROBE, str(output), phase], cwd=output,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            (output / f"{phase}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
            if result.returncode:
                results.append({"phase": phase, "status": "FAIL"})
                break
            results.append(json.loads(result.stdout.strip().splitlines()[-1]))
    passed = checked.returncode == 0 and len(results) == 2 and all(item["status"] == "PASS" for item in results)
    report = {"status": "PASS" if passed else "FAIL", "python": sys.version,
              "dependency_check": checked.returncode == 0, "phases": results, "real_model_calls": False}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Installed-package acceptance: {report['status']}; report: {output / 'report.json'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
