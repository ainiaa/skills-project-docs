"""Collect review evidence from one Codex CLI sample; never infer UI display."""
import argparse
import json
import re
from pathlib import Path

UNKNOWN = 'unknown'
QUESTION_TOOLS = {'request_user_input_async', 'request_user_input'}
REVIEW_INSTRUCTIONS = (
    '读取 interaction-evidence.json 并按每个业务事项分别记录：原问句及来源、工具接受状态、'
    '宿主展示状态。cli_messages 仅是渲染日志线索，可能来自工具输出；结合结构化消息、'
    '最终回复与上下轮语境区分实际请求、引用和仅列未决。calls 中的具体问句证明工具被调用，'
    'accepted 仅表示该调用的返回；async 消息、item_completed 和 accepted:true 都不能证明前端展示。'
    '缺少独立展示证据标未知；若验收依赖展示则标 UNCOVERED，不判虚构或通过。'
    '按冻结业务要求单独检查真正遗漏的事项，不以问号计数或总分替代。'
)


def decoded(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def collect(root):
    root = Path(root)
    result = dict(rollout_status=UNKNOWN, calls=[], assistant_messages=[], async_messages=[], cli_messages=[],
                  final_replies=[], evidence_gaps=[])
    sessions = set()
    for trace in sorted((root / 'logs').glob('trace*.txt')):
        lines = trace.read_text().splitlines()
        # Only the CLI header binds a rollout; echoed file contents cannot bind it.
        header = lines[:lines.index('user')] if 'user' in lines else lines[:16]
        sessions.update(s[12:].strip() for s in header if s.startswith('session id: '))
        for i, s in enumerate(lines):
            if s != 'codex':
                continue
            block = []
            for line in lines[i + 1:]:
                if line in ('codex', 'exec', 'user', 'tokens used') or re.match(r'^\d{4}-\d\d-\d\dT\d\d:', line):
                    break
                block.append(line)
            if block:
                result['cli_messages'].append(dict(source=f'{trace.name}:{i+2}',
                                                   text='\n'.join(block).strip(),
                                                   accepted=UNKNOWN, host_displayed=UNKNOWN))
    for p in sorted((root / 'logs').glob('answer*.txt')):
        result['final_replies'].append(dict(source=p.name, text=p.read_text().strip()))

    matched = set()
    for f in sorted((root / 'codex-home/sessions').rglob('*.jsonl')):
        try:
            events = [(n, json.loads(line)) for n, line in enumerate(f.read_text().splitlines(), 1)
                      if line.strip()]
            if any(not isinstance(e, dict) or not isinstance(e.get('payload'), dict) for _, e in events):
                raise ValueError('Malformed event')
        except (ValueError, UnicodeError):
            result['evidence_gaps'].append('Unreadable rollout: ' + f.name)
            continue
        meta = [e['payload'].get('id') for _, e in events if e.get('type') == 'session_meta']
        if len(meta) != 1 or meta[0] not in sessions:
            continue
        matched.add(meta[0])
        calls, outputs = {}, {}
        turn = None
        for n, e in events:
            p = e.get('payload', {})
            kind = p.get('type')
            source = f'{f.name}:{n}'
            if e.get('type') == 'event_msg' and kind == 'task_started':
                turn = p.get('turn_id')
            if e.get('type') == 'event_msg' and kind == 'item_completed':
                item = p.get('item', {})
                if not isinstance(item, dict):
                    result['evidence_gaps'].append('Unknown runtime item: ' + source)
                    continue
                if (item.get('type') == 'AgentMessage' and item.get('delivery') == 'async'
                        and p.get('thread_id') == meta[0]):
                    result['async_messages'].append(dict(
                        source=source, turn_id=p.get('turn_id'), call_id=item.get('id'),
                        text='\n'.join(c['text'] for c in item.get('content', []) if c.get('type') == 'Text'),
                        host_displayed=UNKNOWN))
            if e.get('type') != 'response_item':
                continue
            key = (turn, p.get('call_id'))
            if kind == 'function_call' and p.get('name') in QUESTION_TOOLS:
                qs = decoded(p.get('arguments')).get('questions')
                questions = [q.get('title') or q.get('question') for q in qs
                             if isinstance(q, dict)] if isinstance(qs, list) else []
                row = dict(source=source, turn_id=turn, tool=p['name'], call_id=key[1],
                           questions=[q for q in questions if isinstance(q, str) and q.strip()] or UNKNOWN,
                           accepted=UNKNOWN, host_displayed=UNKNOWN)
                calls.setdefault(key, []).append((n, row))
                result['calls'].append(row)
            elif kind == 'function_call_output':
                outputs.setdefault(key, []).append((n, decoded(p.get('output')).get('accepted')))
            elif kind == 'message' and p.get('role') == 'assistant':
                text = '\n'.join(c['text'] for c in p.get('content', [])
                                 if c.get('type') == 'output_text')
                result['assistant_messages'].append(dict(source=source, turn_id=turn, text=text))
        for key, rows in calls.items():
            replies = outputs.get(key, [])
            if not key[1] or len(rows) != 1 or len(replies) != 1:
                continue
            start, row = rows[0]
            end, accepted = replies[0]
            if end > start and type(accepted) is bool:
                row.update(accepted=accepted, return_source=f'{f.name}:{end}')
    if matched and matched == sessions and not result['evidence_gaps']:
        result['rollout_status'] = 'matched'
    # Absence of events is never represented as a rejection or a display failure.
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sample', type=Path)
    args = parser.parse_args()
    print(json.dumps(collect(args.sample), ensure_ascii=False, indent=2))
