"""Generated interpretations with explicit availability and labeled basic output."""
import json
import re
from pathlib import PurePosixPath
from .analysis import secrets
from .gitops import Change
from .cloud_ai import generate, result, scrub, settings


def mode_for(ai):
    if ai['status'] == 'completed': return 'gemini-generated-cached' if ai['cached'] else 'gemini-generated'
    return 'template; AI ' + ai['status'] + ' (' + (ai['reason'] or 'no input') + ')'


def protected_changes(changes):
    for c in changes:
        if secrets([Change(c.path, c.old_path, c.base, [], c.added + c.removed)]): return True
        original = '\n'.join(text for _, text in c.added + c.removed)
        if scrub(original) != original: return True
    return False


def diff_context(changes):
    return [dict(file=c.path, removed=c.removed, added=c.added, base_commit=c.base, binary=c.binary) for c in changes]


def explain_result(evidence, store=None, context=None):
    if not settings()['enabled']: ai = result('disabled', 'explicitly_disabled')
    elif not evidence: ai = result('unavailable', 'missing_evidence')
    else:
        ai = generate('explain_history', json.dumps(dict(instruction='Explain in plain English why this code exists using historical evidence. Do not infer a complete timeline from missing data.', line=context)), evidence, store)
    basic = scrub(evidence[0]['body'][:500]) if evidence else 'Historical evidence unavailable; run ingest.'
    return dict(text=ai['text'] or basic, mode=mode_for(ai), ai=ai)


def explain(evidence):
    output = explain_result(evidence)
    return output['text'], output['mode']


def review_changes(store, changes, findings, task='review_changes'):
    if not changes: return result('not_applicable', 'no_changes')
    if not settings()['enabled']: return result('disabled', 'explicitly_disabled')
    if protected_changes(changes): return result('blocked', 'suspected_secret_in_changes')
    evidence = [e for f in findings for e in f.get('evidence', [])]
    context = json.dumps(dict(instruction='Assess actual changes against historical evidence and sampled review patterns. Explain potential safeguard regressions and suggest specific tests/improvements. Do not override deterministic findings. If no relevant evidence exists, explicitly state historical justification is unavailable.', changes=diff_context(changes), basic_findings=[{k:v for k,v in f.items() if k != 'evidence'} for f in findings]))
    return generate(task, context, evidence, store)


def commit_message_result(repo, store):
    changes = repo.changes()
    if not changes: return dict(message='', mode='no-staged-changes', ai=result('not_applicable', 'no_changes'))
    subjects = repo.run('log', '-30', '--format=%s', check=False).splitlines()
    paths = [c.path for c in changes]
    scope = re.sub(r'[^a-zA-Z0-9_-]', '-', PurePosixPath(paths[0]).stem)[:30] or 'code'
    kind = 'docs' if all(p.lower().endswith(('.md','.rst','.txt')) for p in paths) else 'test' if all('test' in p.lower() for p in paths) else 'fix' if any(c.removed for c in changes) else 'feat'
    conventional = [s for s in subjects if re.match(r'[a-z]+(?:\([^)]*\))?!?: ', s)]
    names = ', '.join(PurePosixPath(p).name for p in paths[:3])
    if len(paths)>3: names += f' and {len(paths)-3} more files'
    removed, added = sum(len(c.removed) for c in changes), sum(len(c.added) for c in changes)
    action = 'remove' if removed and not added else 'add' if added and not removed else 'update'
    basic = f'{action} {names}'
    if conventional and len(conventional) >= len(subjects)/2:
        scoped = sum(bool(re.match(r'[a-z]+\(', s)) for s in conventional) >= len(conventional)/2
        basic = (f'{kind}({scope}): ' if scoped else f'{kind}: ') + basic
    elif subjects and sum(s[:1].isupper() for s in subjects) >= len(subjects)/2: basic = basic[0].upper()+basic[1:]
    refs, evidence = set(), []
    for change in changes:
        for line, _ in change.removed:
            try:
                sha = repo.blame(change.old_path, line, change.base)['sha']
                documents = store.evidence(sha)
                evidence.extend(documents)
                refs.update(e['id'] for e in documents if e['kind']=='issue')
            except RuntimeError: pass
    if not settings()['enabled']: ai = result('disabled', 'explicitly_disabled')
    elif protected_changes(changes): ai = result('blocked', 'suspected_secret_in_changes')
    else:
        ai = generate('commit_message', json.dumps(dict(instruction='Write one concise commit subject describing the actual diff. Match the repository convention. Do not assert a bug is fixed without support. No issue references in subject. Return evidence_ids separately when historical evidence is supplied.', changes=diff_context(changes), recent_subjects=subjects, style_example=basic)), evidence, store)
    message = ai['text'] or scrub(basic)
    if refs: message += '\n\nHistorical context: ' + ', '.join(f'#{n}' for n in sorted(refs))
    return dict(message=message, mode=mode_for(ai), ai=ai)


def commit_message(repo, store):
    output = commit_message_result(repo, store)
    return output['message'], output['mode']
